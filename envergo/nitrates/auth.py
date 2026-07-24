"""ProConnect (OIDC) authentication backend pour le simulateur nitrates.

Politique d'auth :
- Aucune creation de compte spontanee. L'admin doit etre pre-provisionne
  par email (cf. management command `provision_admin`).
- Reconciliation prioritaire sur le claim `sub` ProConnect (stable
  meme si l'utilisateur change d'email cote IdP), fallback sur l'email
  pour la 1ere connexion.
- A la 1ere connexion reussie, le `sub` est persiste sur l'utilisateur.
- Tout email inconnu => echec d'auth, redirection ProConnect renvoie
  l'utilisateur sur la page de login admin sans session.
"""

import logging

from django.core.exceptions import SuspiciousOperation
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger(__name__)


class ProConnectBackend(OIDCAuthenticationBackend):
    """Backend OIDC qui refuse toute creation de compte spontanee."""

    def filter_users_by_claims(self, claims):
        """Match priorite `sub` puis `email`. Pas de creation."""
        sub = claims.get("sub")
        email = claims.get("email")

        if sub:
            users = self.UserModel.objects.filter(proconnect_sub=sub)
            if users.exists():
                return users

        if not email:
            return self.UserModel.objects.none()

        # Fallback email : n'existe que pour la 1re connexion, avant que
        # `proconnect_sub` soit persiste (ensuite le match se fait sur `sub`).
        # On ne fait confiance a l'email que s'il est verifie par l'IdP, pour
        # ne pas rattacher un compte pre-provisionne sur un email non prouve
        # (F3 pentest 2026-06-18, refs #150). Aucune creation ici : create_user
        # leve SuspiciousOperation, donc le pire cas reste borne.
        if claims.get("email_verified") is False:
            return self.UserModel.objects.none()

        return self.UserModel.objects.filter(email__iexact=email)

    def create_user(self, claims):
        """Refuse la creation : seuls les admins pre-provisionnes peuvent se connecter."""
        email = claims.get("email", "<absent>")
        logger.warning("ProConnect login refused: email %s not pre-provisioned", email)
        raise SuspiciousOperation(
            "Cet utilisateur n'est pas autorise a se connecter via ProConnect. "
            "Contactez un administrateur pour faire creer votre compte."
        )

    def update_user(self, user, claims):
        """Persiste le sub a la 1ere connexion + maj nom."""
        sub = claims.get("sub")
        if sub and not user.proconnect_sub:
            user.proconnect_sub = sub
        # Nom : ProConnect renvoie given_name + usual_name. On concatene
        # dans User.name si vide (sinon on respecte ce qu'un admin a saisi).
        if not user.name:
            given = claims.get("given_name", "").strip()
            usual = claims.get("usual_name", "").strip()
            full = " ".join(p for p in (given, usual) if p)
            if full:
                user.name = full
        # Garantir l'acces admin (pre-provision implique is_staff=True
        # mais on est defensif au cas ou un compte legacy se connecte).
        if not user.is_staff:
            logger.warning(
                "ProConnect login: user %s is not staff, denying admin access",
                user.email,
            )
        user.save()
        return user

    def verify_claims(self, claims):
        """Email obligatoire. ProConnect le marque obligatoire mais on verrouille."""
        if not claims.get("email"):
            logger.warning("ProConnect claims missing email: %s", list(claims))
            return False
        return super().verify_claims(claims)

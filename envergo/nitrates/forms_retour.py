"""Formulaire de validation des retours utilisateurs (#284/#287).

Valide côté serveur les données postées par le front (popup feedback fin de
simulation, capture email région fermée) avant création du RetourUtilisateur.
RGPD : un email n'est accepté que si le consentement est coché.
"""

from django import forms

from envergo.nitrates.models_retour import RetourUtilisateur


class RetourUtilisateurForm(forms.ModelForm):
    class Meta:
        model = RetourUtilisateur
        fields = (
            "type",
            "note",
            "commentaire",
            "email",
            "consentement_email",
            "region_code",
            "contexte",
        )

    def clean_note(self):
        note = self.cleaned_data.get("note")
        if note is not None and (note < 0 or note > 5):
            raise forms.ValidationError("La note doit être comprise entre 0 et 5.")
        return note

    def clean(self):
        cleaned = super().clean()
        type_ = cleaned.get("type")
        note = cleaned.get("note")
        email = (cleaned.get("email") or "").strip()
        consentement = cleaned.get("consentement_email")

        # Un feedback doit porter une note (0-5) ; un intérêt région n'en a pas.
        if type_ == RetourUtilisateur.Type.FEEDBACK and note is None:
            self.add_error("note", "Une note (0 à 5) est requise pour un feedback.")

        # RGPD : pas d'email sans consentement explicite. Si l'email est fourni
        # mais la case non cochée, on IGNORE l'email plutôt que d'échouer (le
        # reste du retour, note/commentaire, reste utile et anonyme).
        if email and not consentement:
            cleaned["email"] = ""
            cleaned["consentement_email"] = False

        # Un intérêt région sans email n'a aucune valeur : on l'exige.
        if type_ == RetourUtilisateur.Type.INTERET_REGION and not cleaned.get("email"):
            self.add_error(
                "email",
                "Un email (avec consentement) est requis pour être tenu au "
                "courant de l'ouverture d'une région.",
            )

        return cleaned

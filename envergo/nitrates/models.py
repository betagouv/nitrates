from django.db import models


class RpgCulture(models.Model):
    """Code culture du Registre Parcellaire Graphique (PAC).

    Reference officielle IGN/ASP, dispo en CSV sur data.gouv. 144 codes en 2024.
    Le RPG stocke un code a 3 lettres par parcelle (ex BTH = ble tendre), on
    se sert de cette table pour mapper vers un libelle lisible et un groupe
    de culture (ex BTH -> "ble tendre" / groupe "Cereales a paille").

    Le groupe sera particulierement utile pour le YAML PAN qui parle de
    categories ("cereales", "olegineux") plutot que de trigrammes.
    """

    code = models.CharField(max_length=3, primary_key=True)
    libelle = models.CharField(max_length=255)
    code_groupe = models.CharField(max_length=10, blank=True)
    libelle_groupe = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Code culture RPG"
        verbose_name_plural = "Codes culture RPG"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.libelle}"

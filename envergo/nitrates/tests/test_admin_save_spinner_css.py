"""Le CSS de l'editeur YAML doit contenir une regle .htmx-request qui
affiche un overlay "Sauvegarde en cours" pendant un POST inline. Cela
donne un feedback visuel a l'utilisateur, surtout sur staging ou la
latence n'est pas instantanee.
"""

from pathlib import Path


def test_css_contains_htmx_request_spinner_rule():
    css_path = (
        Path(__file__).resolve().parent.parent.parent
        / "static"
        / "nitrates_admin"
        / "yaml_tree.css"
    )
    content = css_path.read_text(encoding="utf-8")
    # La regle doit cibler .yaml-tree__inline-form.htmx-request
    assert ".yaml-tree__inline-form.htmx-request" in content
    # Et exposer un message "Sauvegarde" via ::before
    assert "Sauvegarde" in content
    # Et un overlay via ::after
    assert "::after" in content

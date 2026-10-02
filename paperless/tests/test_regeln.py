import regeln

TEXT = "Rechnung Nr. 4711 Beispiel Hosting GmbH Gesamtbetrag 49,99 EUR vom 01.09.2026 vielen Dank"


def dok(id, content=TEXT, added="2026-09-01T10:00:00Z", title="Rechnung"):
    return {"id": id, "title": title, "content": content, "added": added, "created": "2026-09-01"}


def test_inhaltsgleich_trotz_leerraum_und_gross_klein():
    a, b = dok(1), dok(2, content=TEXT.upper().replace(" ", "  \n"))
    assert [[d["id"] for d in g] for g in regeln.gruppen([a, b])] == [[1, 2]]


def test_unterschiedlicher_inhalt_keine_gruppe():
    assert regeln.gruppen([dok(1), dok(2, content=TEXT.replace("4711", "4712"))]) == []


def test_kurzer_oder_leerer_text_nie_duplikat():
    assert regeln.gruppen([dok(1, content=""), dok(2, content="")]) == []
    assert regeln.gruppen([dok(1, content="Seite 1"), dok(2, content="Seite 1")]) == []


def test_loeschplan_behaelt_aeltestes():
    g = [dok(5, added="2026-09-03T00:00:00Z"), dok(3, added="2026-09-01T00:00:00Z"), dok(9, added="2026-09-02T00:00:00Z")]
    behalten, loeschen = regeln.loeschplan(g)
    assert behalten["id"] == 3 and [d["id"] for d in loeschen] == [5, 9]


def test_noch_gleich_erkennt_aenderung():
    assert regeln.noch_gleich(dok(1), dok(2))
    assert not regeln.noch_gleich(dok(1), dok(2, content=TEXT + " Nachtrag"))

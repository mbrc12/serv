"""Human labels for colour keys."""

from __future__ import annotations

from serv.config import Accents, CodePalette, Palette
from serv.labels import label_for, load_labels


def test_every_colour_key_has_a_label() -> None:
    labels = load_labels()
    for section, dataclass in (
        ("palette", Palette),
        ("accents", Accents),
        ("code", CodePalette),
    ):
        assert set(labels[section]) == set(dataclass.__dataclass_fields__)


def test_labels_are_readable_not_identifiers() -> None:
    assert label_for("palette", "zebra") == "Striped rows"
    assert label_for("palette", "bg") == "Page background"
    assert label_for("code", "tag") == "Tags and attributes"
    for section in ("palette", "accents", "code"):
        for key in load_labels()[section]:
            label = label_for(section, key)
            assert "_" not in label
            assert label != key
            assert label[0].isupper()


def test_unknown_key_falls_back_to_a_humanised_name() -> None:
    assert label_for("palette", "some_new_key") == "Some new key"

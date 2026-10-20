"""A small native settings window, plus the start-at-login question.

Built with AppKit directly (PyObjC ships with rumps, so no extra dependency).
The window edits every value in ``~/.config/serv/serv.toml`` and applies the
result to a running server without a restart.

Widgets are the modern macOS ones: a segmented control for the sections, rounded
cards for grouping, list rows instead of a raw text area for the glob patterns,
and rounded colour swatches that open the system colour panel.

Only the port needs a restart to take effect, because the listening socket is
bound at startup; the window says so instead of pretending otherwise.
"""

from __future__ import annotations

from dataclasses import fields
import re
from pathlib import Path
from typing import Callable

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSAlert,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSBezierPath,
    NSBox,
    NSBoxCustom,
    NSButton,
    NSColor,
    NSColorPanel,
    NSColorSpace,
    NSFont,
    NSFontManager,
    NSImage,
    NSImageView,
    NSImageScaleProportionallyUpOrDown,
    NSInsetRect,
    NSLayoutConstraint,
    NSMakeRect,
    NSPopUpButton,
    NSSegmentedControl,
    NSSegmentStyleAutomatic,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSObject

from . import fonts, launchagent, schemes
from .config import Config, ConfigError, load_config, parse_config, save_config
from .locations import user_config_path
from .resources import data_dir

WINDOW_WIDTH = 620
WINDOW_HEIGHT = 500
MARGIN = 20
CARD_TOP = WINDOW_HEIGHT - 118
CARD_HEIGHT = CARD_TOP - 70
CARD_INSET = 18

#: Label of the popup entry that opens the system font panel.
SYSTEM_FONT_ITEM = "System font…"

#: Called with the saved config so a running server can apply it.
SaveCallback = Callable[[Config], None]


# --------------------------------------------------------------- colour helpers

_HEX = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_RGBA = re.compile(r"^rgba?\(([^)]*)\)$")


def colour_from_css(value: str) -> NSColor:
    """Turn a CSS colour from the config into an NSColor for a swatch."""
    match = _HEX.match(value.strip())
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        if len(digits) == 6:
            digits += "ff"
        return NSColor.colorWithSRGBRed_green_blue_alpha_(
            int(digits[0:2], 16) / 255,
            int(digits[2:4], 16) / 255,
            int(digits[4:6], 16) / 255,
            int(digits[6:8], 16) / 255,
        )
    match = _RGBA.match(value.strip())
    if match:
        parts = [part.strip() for part in match.group(1).split(",")]
        numbers = [float(part) for part in parts[:3]]
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return NSColor.colorWithSRGBRed_green_blue_alpha_(
            numbers[0] / 255, numbers[1] / 255, numbers[2] / 255, alpha
        )
    if value.strip() == "transparent":
        return NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 0)
    return NSColor.blackColor()


def css_from_colour(colour: NSColor) -> str:
    """Turn an NSColor back into the shortest accurate CSS colour."""
    converted = colour.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
    if converted is None:
        return "#000000"
    red, green, blue, alpha = (
        converted.redComponent(),
        converted.greenComponent(),
        converted.blueComponent(),
        converted.alphaComponent(),
    )
    if alpha <= 0.004:
        return "transparent"
    if alpha >= 0.996:
        return (
            f"#{int(round(red * 255)):02x}"
            f"{int(round(green * 255)):02x}"
            f"{int(round(blue * 255)):02x}"
        )
    return (
        f"rgba({int(round(red * 255))}, {int(round(green * 255))}, "
        f"{int(round(blue * 255))}, {round(alpha, 3)})"
    )


# --------------------------------------------------------------------- widgets


class FlippedView(NSView):
    """A view whose origin is the top-left corner, so rows count downwards."""

    def isFlipped(self) -> bool:  # noqa: N802 - AppKit naming
        return True


class SwatchView(NSView):
    """A rounded colour patch that opens the system colour panel when clicked."""

    def initWithFrame_colour_(self, rect, colour: NSColor):
        self = objc.super(SwatchView, self).initWithFrame_(rect)
        if self is None:
            return None
        self._colour = colour
        return self

    def setOnChange_(self, callback) -> None:  # noqa: N802 - AppKit naming
        self._on_change = callback

    def setColour_(self, colour: NSColor) -> None:  # noqa: N802 - AppKit naming
        self._colour = colour
        self.setNeedsDisplay_(True)

    def colour(self) -> NSColor:
        return self._colour

    def drawRect_(self, rect) -> None:  # noqa: N802 - AppKit naming
        bounds = NSInsetRect(self.bounds(), 0.5, 0.5)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 5.0, 5.0)
        # Transparent and translucent colours sit on a light plate so the alpha
        # is visible instead of looking like a hole in the window.
        NSColor.whiteColor().setFill()
        path.fill()
        self._colour.setFill()
        path.fill()
        NSColor.separatorColor().setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

    def mouseDown_(self, event) -> None:  # noqa: N802 - AppKit naming
        panel = NSColorPanel.sharedColorPanel()
        panel.setColor_(self._colour)
        panel.setTarget_(self)
        panel.setAction_("panelChanged:")
        panel.orderFront_(None)

    def panelChanged_(self, sender) -> None:  # noqa: N802 - AppKit naming
        self.setColour_(sender.color())
        if getattr(self, "_on_change", None) is not None:
            self._on_change()

    def acceptsFirstMouse_(self, event) -> bool:  # noqa: N802 - AppKit naming
        return True

    def isFlipped(self) -> bool:  # noqa: N802 - AppKit naming
        return True


class IndexedButton(NSButton):
    """A push button that remembers which row it belongs to."""

    def initWithTitle_row_target_action_(self, title, row, target, action):
        self = objc.super(IndexedButton, self).initWithFrame_(NSMakeRect(0, 0, 26, 24))
        if self is None:
            return None
        self._row = row
        self.setTitle_(title)
        self.setBezelStyle_(NSBezelStyleRounded)
        self.setTarget_(target)
        self.setAction_(action)
        return self

    def row(self) -> int:
        return self._row


def _label(text: str, size: float = 12.0, bold: bool = False, muted: bool = False) -> NSTextField:
    """Return a non-editable label."""
    view = NSTextField.labelWithString_(text)
    view.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if muted:
        view.setTextColor_(NSColor.secondaryLabelColor())
    return view


def _field(value: str, width: int = 120) -> NSTextField:
    """Return a single-line text field with a fixed width."""
    control = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, 22))
    control.setStringValue_(value)
    control.setFont_(NSFont.systemFontOfSize_(12))
    control.setAlignment_(1)  # right-aligned values read better in a form
    control.setTranslatesAutoresizingMaskIntoConstraints_(False)
    NSLayoutConstraint.activateConstraints_(
        [
            control.widthAnchor().constraintEqualToConstant_(width),
            control.heightAnchor().constraintEqualToConstant_(22),
        ]
    )
    return control


def _button(title: str, target, action: str, width: int = 90) -> NSButton:
    """Return a standard push button."""
    control = NSButton.buttonWithTitle_target_action_(title, target, action)
    control.setBezelStyle_(NSBezelStyleRounded)
    control.setFrame_(NSMakeRect(0, 0, width, 26))
    return control


def _card(frame) -> NSBox:
    """Return a rounded grouping card."""
    box = NSBox.alloc().initWithFrame_(frame)
    box.setBoxType_(NSBoxCustom)
    box.setBorderWidth_(1)
    box.setBorderColor_(NSColor.separatorColor())
    box.setCornerRadius_(10)
    box.setFillColor_(NSColor.controlBackgroundColor())
    box.setTitlePosition_(0)
    box.setTitle_("")
    # The card lays its rows out top-down like a form, so its content view has
    # to be flipped; NSBox's own content view starts at the bottom-left.
    box.setContentView_(
        FlippedView.alloc().initWithFrame_(box.contentView().frame())
    )
    return box


def _app_icon() -> NSImage | None:
    """Return the menu-bar glyph, used as the window's little logo."""
    candidate = data_dir() / "tray" / "servTemplate@4x.png"
    if not candidate.is_file():
        return None
    return NSImage.alloc().initWithContentsOfFile_(str(candidate))


# ------------------------------------------------------------------- the window


class SettingsController(NSObject):
    """Owns the settings window and applies edits to the config file."""

    def initWithConfig_callback_(self, config: Config, callback: SaveCallback | None):
        self = objc.super(SettingsController, self).init()
        if self is None:
            return None
        self._config = config
        self._callback = callback
        self._fields: dict[str, NSTextField] = {}
        self._swatches: dict[str, SwatchView] = {}
        self._glob_fields: list[NSTextField] = []
        self._font_popups: dict[str, NSPopUpButton] = {}
        self._font_role: str | None = None
        self._login_checkbox = None
        self._standalone = False
        # Draft values survive a section switch, so a tab change never loses an
        # edit made in the tab being left.
        self._draft: dict[str, str] = self._values_from_config(config)
        self._section = 0
        self._build_window()
        self._window.setDelegate_(self)
        return self

    @staticmethod
    @objc.python_method
    def _values_from_config(config: Config) -> dict[str, str]:
        values: dict[str, str] = {
            "server.port": str(config.server.port),
            "server.max_render_bytes": str(config.server.max_render_bytes),
            "cache.entries": str(config.cache.entries),
            "server.no_process": "\n".join(config.server.no_process),
        }
        for section, mapping in (
            ("palette", config.palette),
            ("accents", config.accents),
            ("code", config.code),
        ):
            for field in fields(mapping):
                values[f"{section}.{field.name}"] = getattr(mapping, field.name)
        for field in fields(config.type):
            values[f"type.{field.name}"] = getattr(config.type, field.name)
        for field in fields(config.layout):
            values[f"layout.{field.name}"] = getattr(config.layout, field.name)
        return values

    # ------------------------------------------------------------- building

    @objc.python_method
    def _build_window(self) -> None:
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("serv settings")
        self._window.setReleasedWhenClosed_(False)
        self._window.center()
        content = self._window.contentView()

        content.addSubview_(self._build_header())
        content.addSubview_(self._build_sections())
        self._card = _card(NSMakeRect(MARGIN, 70, WINDOW_WIDTH - 2 * MARGIN, CARD_HEIGHT))
        content.addSubview_(self._card)
        self._render_section()
        content.addSubview_(self._build_footer())

    @objc.python_method
    def _build_header(self) -> NSView:
        header = NSView.alloc().initWithFrame_(
            NSMakeRect(0, WINDOW_HEIGHT - 76, WINDOW_WIDTH, 76)
        )
        icon = _app_icon()
        text_left = MARGIN
        if icon is not None:
            view = NSImageView.alloc().initWithFrame_(NSMakeRect(MARGIN, 22, 30, 30))
            view.setImage_(icon)
            view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            header.addSubview_(view)
            text_left = MARGIN + 42

        title = _label("serv", size=15, bold=True)
        title.setFrame_(NSMakeRect(text_left, 38, WINDOW_WIDTH - text_left - MARGIN, 20))
        subtitle = _label(
            f"Local file server · http://localhost:{self._config.server.port}/",
            size=11,
            muted=True,
        )
        subtitle.setFrame_(NSMakeRect(text_left, 22, WINDOW_WIDTH - text_left - MARGIN, 16))
        header.addSubview_(title)
        header.addSubview_(subtitle)
        return header

    @objc.python_method
    def _build_sections(self) -> NSSegmentedControl:
        control = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(MARGIN, CARD_TOP + 12, 300, 24)
        )
        control.setSegmentCount_(3)
        for index, title in enumerate(("General", "Colours", "Type & Layout")):
            control.setLabel_forSegment_(title, index)
            control.setWidth_forSegment_(100 if index == 0 else (84 if index == 1 else 116), index)
        control.setSegmentStyle_(NSSegmentStyleAutomatic)
        control.setSelectedSegment_(0)
        control.setTarget_(self)
        control.setAction_("sectionChanged:")
        return control

    @objc.python_method
    def _build_footer(self) -> NSView:
        footer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, 62))
        reveal = _button("Show config file", self, "reveal:", 150)
        reveal.setFrame_(NSMakeRect(MARGIN, 18, 150, 28))
        footer.addSubview_(reveal)

        cancel = _button("Cancel", self, "cancel:", 86)
        cancel.setKeyEquivalent_("\x1b")
        cancel.setFrame_(NSMakeRect(WINDOW_WIDTH - 194, 18, 86, 28))
        footer.addSubview_(cancel)

        save = _button("Save", self, "save:", 84)
        save.setKeyEquivalent_("\r")
        save.setFrame_(NSMakeRect(WINDOW_WIDTH - 100, 18, 84, 28))
        footer.addSubview_(save)
        return footer

    # --------------------------------------------------------------- sections

    @objc.python_method
    def _clear_card(self) -> None:
        for view in list(self._card.contentView().subviews()):
            view.removeFromSuperview()
        self._fields.clear()
        self._swatches.clear()
        self._glob_fields.clear()

    @objc.python_method
    def _render_section(self) -> None:
        self._clear_card()
        if self._section == 0:
            self._render_general()
        elif self._section == 1:
            self._render_colours()
        else:
            self._render_type()

    @objc.python_method
    def _render_general(self) -> None:
        card = self._card.contentView()
        width = WINDOW_WIDTH - 2 * MARGIN
        rows = (
            ("server.port", "Port", 96),
            ("server.max_render_bytes", "Largest rendered file (bytes)", 120),
            ("cache.entries", "Cached pages", 96),
        )
        y = CARD_INSET
        for key, caption, field_width in rows:
            label = _label(caption)
            label.setFrame_(NSMakeRect(CARD_INSET, y + 3, 240, 18))
            field = _field(self._draft[key], field_width)
            field.setFrame_(NSMakeRect(width - CARD_INSET - field_width, y, field_width, 22))
            card.addSubview_(label)
            card.addSubview_(field)
            self._fields[key] = field
            y += 30

        heading = _label("Served verbatim", size=11, bold=True, muted=True)
        heading.setFrame_(NSMakeRect(CARD_INSET, y + 10, 200, 14))
        hint = _label("matched files are sent as-is, without rendering", size=11, muted=True)
        hint.setFrame_(NSMakeRect(CARD_INSET + 108, y + 10, 360, 14))
        card.addSubview_(heading)
        card.addSubview_(hint)
        y += 30

        patterns = [line for line in self._draft["server.no_process"].splitlines() if line.strip()]
        for pattern in patterns:
            field = _field(pattern, width - 2 * CARD_INSET - 34)
            field.setAlignment_(0)
            field.setFrame_(NSMakeRect(CARD_INSET, y, width - 2 * CARD_INSET - 34, 22))
            remove = IndexedButton.alloc().initWithTitle_row_target_action_(
                "−", len(self._glob_fields), self, "removeGlob:"
            )
            remove.setFrame_(NSMakeRect(width - CARD_INSET - 26, y - 1, 26, 24))
            card.addSubview_(field)
            card.addSubview_(remove)
            self._glob_fields.append(field)
            y += 28

        add = _button("+ Add pattern", self, "addGlob:", 120)
        add.setFrame_(NSMakeRect(CARD_INSET, y + 2, 120, 24))
        card.addSubview_(add)
        y += 36

        checkbox = NSButton.checkboxWithTitle_target_action_("Start serv at login", None, None)
        checkbox.setFrame_(NSMakeRect(CARD_INSET, y + 6, 320, 22))
        checkbox.setState_(1 if launchagent.is_installed() else 0)
        card.addSubview_(checkbox)
        self._login_checkbox = checkbox

    @objc.python_method
    def _render_colours(self) -> None:
        card = self._card.contentView()
        width = WINDOW_WIDTH - 2 * MARGIN
        inner = width - 2 * CARD_INSET
        columns = 5
        cell = inner // columns
        row_height = 28
        y = CARD_INSET - 8

        scheme_label = _label("Scheme")
        scheme_label.setFrame_(NSMakeRect(CARD_INSET, y + 4, 60, 18))
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(CARD_INSET + 62, y, 220, 26), False
        )
        self._scheme_keys = [scheme.key for scheme in schemes.load_schemes()] + [schemes.CUSTOM]
        popup.addItemsWithTitles_([schemes.label_for(key) for key in self._scheme_keys])
        popup.selectItemWithTitle_(schemes.label_for(schemes.name_for_values(self._draft)))
        popup.setTarget_(self)
        popup.setAction_("schemeChanged:")
        card.addSubview_(scheme_label)
        card.addSubview_(popup)
        self._scheme_popup = popup
        y += 28
        for title, section, mapping in (
            ("Interface", "palette", self._config.palette),
            ("Accents", "accents", self._config.accents),
            ("Source", "code", self._config.code),
        ):
            heading = _label(title, size=11, bold=True, muted=True)
            heading.setFrame_(NSMakeRect(CARD_INSET, y, 200, 14))
            card.addSubview_(heading)
            y += 17
            names = [field.name for field in fields(mapping)]
            for index, name in enumerate(names):
                row, column = divmod(index, columns)
                x = CARD_INSET + column * cell
                cell_y = y + row * row_height
                key = f"{section}.{name}"
                swatch = SwatchView.alloc().initWithFrame_colour_(
                    NSMakeRect(x, cell_y, 24, 24), colour_from_css(self._draft[key])
                )
                caption = _label(name.replace("_", " "), size=11)
                caption.setFrame_(NSMakeRect(x + 32, cell_y + 5, cell - 34, 16))
                swatch.setOnChange_(self._swatch_changed)
                card.addSubview_(swatch)
                card.addSubview_(caption)
                self._swatches[key] = swatch
            rows = (len(names) + columns - 1) // columns
            y += rows * row_height + 8

    @objc.python_method
    def _render_type(self) -> None:
        card = self._card.contentView()
        width = WINDOW_WIDTH - 2 * MARGIN
        y = CARD_INSET - 2
        for role, caption in (("reading", "Reading font"), ("mono", "Monospace font")):
            label = _label(caption)
            label.setFrame_(NSMakeRect(CARD_INSET, y + 5, 240, 18))
            card.addSubview_(label)
            card.addSubview_(self._font_popup(role, y))
            y += 30

        rows = (
            ("type.md_size", "Markdown size", 96),
            ("type.md_table", "Table size", 96),
            ("type.code_size", "Code size", 96),
            ("layout.md_width", "Markdown width", 96),
            ("layout.md_gutter", "Markdown gutter", 96),
            ("layout.listing_width", "Listing width", 96),
        )
        for key, caption, field_width in rows:
            label = _label(caption)
            label.setFrame_(NSMakeRect(CARD_INSET, y + 3, 240, 18))
            field = _field(self._draft[key], field_width)
            field.setFrame_(NSMakeRect(width - CARD_INSET - field_width, y, field_width, 22))
            card.addSubview_(label)
            card.addSubview_(field)
            self._fields[key] = field
            y += 30

    # -------------------------------------------------------------- actions

    @objc.python_method
    def _font_popup(self, role: str, y: float) -> NSPopUpButton:
        """Return a popup listing the catalogue for a role plus the system panel."""
        width = WINDOW_WIDTH - 2 * MARGIN
        catalogue = fonts.choices_for(role)
        names = [choice.name for choice in catalogue]
        current = self._draft.get(f"type.{role}", "")
        items = list(names)
        if current and current not in items:
            items.insert(0, current)
        items.append(SYSTEM_FONT_ITEM)

        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(width - CARD_INSET - 240, y, 240, 26), False
        )
        popup.addItemsWithTitles_(items)
        popup.selectItemWithTitle_(current if current in items else SYSTEM_FONT_ITEM)
        popup.setTarget_(self)
        popup.setAction_("fontRoleChanged:")
        self._font_popups[role] = popup
        return popup

    def fontRoleChanged_(self, sender) -> None:  # noqa: N802 - ObjC selector
        role = next((key for key, popup in self._font_popups.items() if popup is sender), None)
        if role is None:
            return
        title = sender.titleOfSelectedItem()
        if title == SYSTEM_FONT_ITEM:
            self._font_role = role
            manager = NSFontManager.sharedFontManager()
            manager.setTarget_(self)
            manager.setAction_("systemFontChanged:")
            manager.orderFrontFontPanel_(None)
            return
        choice = next((entry for entry in fonts.choices_for(role) if entry.name == title), None)
        if choice is None:
            return
        self._draft[f"type.{role}"] = choice.name
        self._draft[f"type.{role}_weights"] = choice.weights

    def systemFontChanged_(self, sender) -> None:  # noqa: N802 - ObjC selector
        """Apply a family chosen in the system font panel."""
        role = self._font_role
        if role is None:
            return
        chosen = sender.convertFont_(NSFont.systemFontOfSize_(13))
        family = chosen.familyName() if chosen is not None else None
        if not family:
            return
        self._draft[f"type.{role}"] = family
        # A family from the panel may also be a Google font; keep its import.
        self._draft[f"type.{role}_weights"] = fonts.weights_for(role, family) or ""
        self._render_section()

    @objc.python_method
    def _stash(self) -> None:
        """Copy the visible controls into the draft."""
        for key, field in self._fields.items():
            self._draft[key] = field.stringValue()
        for key, swatch in self._swatches.items():
            self._draft[key] = css_from_colour(swatch.colour())
        if self._glob_fields:
            self._draft["server.no_process"] = "\n".join(
                field.stringValue() for field in self._glob_fields
            )

    def schemeChanged_(self, sender) -> None:  # noqa: N802 - ObjC selector
        index = sender.indexOfSelectedItem()
        if index < 0 or index >= len(self._scheme_keys):
            return
        key = self._scheme_keys[index]
        if key == schemes.CUSTOM:
            return
        self._stash()
        chosen = next(scheme for scheme in schemes.load_schemes() if scheme.key == key)
        schemes.apply_to_values(self._draft, chosen)
        self._render_section()

    @objc.python_method
    def _swatch_changed(self) -> None:
        """Keep the scheme dropdown honest when a swatch is edited by hand."""
        if getattr(self, "_scheme_popup", None) is None:
            return
        self._stash()
        key = schemes.name_for_values(self._draft)
        self._scheme_popup.selectItemWithTitle_(schemes.label_for(key))

    def sectionChanged_(self, sender) -> None:  # noqa: N802 - ObjC selector
        self._stash()
        self._section = sender.selectedSegment()
        self._render_section()

    def addGlob_(self, _sender) -> None:  # noqa: N802 - ObjC selector
        self._stash()
        lines = [line for line in self._draft["server.no_process"].splitlines() if line.strip()]
        lines.append("~/")
        self._draft["server.no_process"] = "\n".join(lines)
        self._render_section()

    def removeGlob_(self, sender) -> None:  # noqa: N802 - ObjC selector
        self._stash()
        lines = [line for line in self._draft["server.no_process"].splitlines() if line.strip()]
        index = sender.row() if isinstance(sender, IndexedButton) else None
        if index is not None and 0 <= index < len(lines):
            lines.pop(index)
        self._draft["server.no_process"] = "\n".join(lines)
        self._render_section()

    @objc.python_method
    def show(self) -> None:
        """Bring the window to the front."""
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _collect(self) -> dict:
        """Read every control into a TOML-shaped dict."""
        self._stash()
        data: dict[str, dict] = {}
        for key, value in self._draft.items():
            section, name = key.split(".", 1)
            data.setdefault(section, {})[name] = value
        data["server"]["no_process"] = [
            line.strip() for line in self._draft["server.no_process"].splitlines() if line.strip()
        ]
        for key in ("server.port", "cache.entries", "server.max_render_bytes"):
            section, name = key.split(".", 1)
            data[section][name] = int(self._draft[key])
        return data

    @objc.python_method
    def _apply_login_setting(self, wanted: bool) -> str | None:
        """Install or remove the LaunchAgent; return an error message on failure."""
        try:
            if wanted and not launchagent.is_installed():
                launchagent.install(Path.home())
            elif not wanted and launchagent.is_installed():
                launchagent.uninstall()
        except Exception as error:  # noqa: BLE001 - surface any launchctl failure
            return f"Could not update the login item: {error}"
        return None

    def save_(self, _sender) -> None:  # noqa: N802 - ObjC selector
        try:
            config = parse_config(self._collect(), user_config_path())
        except ConfigError as error:
            self._alert("These settings cannot be saved", str(error))
            return
        except ValueError as error:
            self._alert("These settings cannot be saved", f"Not a number: {error}")
            return

        login_error = self._apply_login_setting(bool(self._login_checkbox.state()))
        try:
            save_config(config)
        except (ConfigError, OSError) as error:
            self._alert("Could not write the config file", str(error))
            return

        if self._callback is not None:
            self._callback(config)
        if login_error:
            self._alert("Settings saved, but the login item failed", login_error)
        elif config.server.port != self._config.server.port:
            self._alert("Settings saved", "The new port takes effect after serv restarts.")
        self._config = config
        self._window.performClose_(None)

    def windowWillClose_(self, _notification) -> None:  # noqa: N802 - ObjC selector
        """Quit when the settings window closes and no server is attached."""
        if self._standalone:
            NSApplication.sharedApplication().terminate_(None)

    def cancel_(self, _sender) -> None:  # noqa: N802 - ObjC selector
        self._window.performClose_(None)

    def reveal_(self, _sender) -> None:  # noqa: N802 - ObjC selector
        path = user_config_path()
        if not path.is_file():
            try:
                save_config(self._config)
            except (ConfigError, OSError) as error:
                self._alert("Could not write the config file", str(error))
                return
        NSWorkspace.sharedWorkspace().selectFile_inFileViewerRootedAtPath_(str(path), "")

    @objc.python_method
    def _alert(self, title: str, detail: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_("OK")
        alert.runModal()


def show_settings(
    config: Config,
    callback: SaveCallback | None = None,
    *,
    standalone: bool = False,
) -> SettingsController:
    """Open the settings window, running its own event loop when standalone."""
    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = SettingsController.alloc().initWithConfig_callback_(config, callback)
    controller._standalone = standalone
    controller.show()
    if standalone:
        application.run()
    return controller


def ask_start_at_login_if_needed() -> bool | None:
    """Ask the start-at-login question once, on the very first launch.

    Returns None when a user config already exists, so the question appears
    exactly once. The answer is remembered by writing the config file, which
    also means the settings window opens on a real file from then on.
    """
    if user_config_path().is_file():
        return None
    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Start serv at login?")
    alert.setInformativeText_(
        "serv can start automatically and live in the menu bar, so "
        "http://localhost:1002/ always works. You can change this later in "
        "serv settings."
    )
    alert.addButtonWithTitle_("Start at Login")
    alert.addButtonWithTitle_("Not Now")
    wanted = alert.runModal() == 1000
    if wanted:
        try:
            launchagent.install(Path.home())
        except Exception as error:  # noqa: BLE001 - never block the app
            print(f"serv: could not install the login item: {error}", flush=True)
    try:
        save_config(load_config())
    except (ConfigError, OSError) as error:
        print(f"serv: could not write {user_config_path()}: {error}", flush=True)
    return wanted

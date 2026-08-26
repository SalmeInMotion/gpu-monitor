"""Windows app template — Nocturne look, user-tunable theme + accent,
frameless chrome, JSON settings, logging, Supervisor bridge.

    import sys; sys.path.insert(0, r"C:\\IA\\Tools\\Windows\\Template")
    from app_template import create_app, FramelessWindow, SettingsDialog
"""

__version__ = "0.5.0"

from .app import AppContext, create_app
from .effects import install_hover_reveal, remove_hover_reveal
from .settings import Settings
from .settings_dialog import SettingsDialog, Swatch
from .presets import BLURBS, PRESETS
from .theme import ThemeManager, current_tokens
from .tokens import ACCENT_SWATCHES, ORIGINAL_ACCENT, build_tokens
from .window import FramelessWindow, TitleBar, WindowButton

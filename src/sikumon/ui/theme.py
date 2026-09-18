"""Centralized visual system for the Sikumon desktop application."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    background: str = "#F7F4EE"
    surface: str = "#FCFAF6"
    surface_secondary: str = "#EEE8DE"
    border: str = "#DED6CA"
    text: str = "#2D2925"
    text_secondary: str = "#766F67"
    text_muted: str = "#9A9289"
    accent: str = "#8B6F47"
    accent_hover: str = "#765C3A"
    accent_pressed: str = "#684F31"
    highlight: str = "#F3E8D5"
    success: str = "#667A68"
    success_surface: str = "#E8EEE7"
    warning: str = "#A47B42"
    warning_surface: str = "#F5EBDD"
    danger: str = "#9B514A"
    danger_surface: str = "#F5E6E3"
    disabled: str = "#E8E3DC"
    disabled_text: str = "#AAA39A"


COLORS = Palette()


def apply_application_theme(app: QApplication) -> None:
    """Apply the Windows-safe font, palette, and reusable widget stylesheet."""

    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS.background))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS.surface_secondary))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS.surface))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS.highlight))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS.text))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLESHEET)


APP_STYLESHEET = f"""
* {{
    font-family: "Segoe UI";
    color: {COLORS.text};
}}
QMainWindow, QDialog, QMessageBox {{ background: {COLORS.background}; }}
QToolTip {{
    background: {COLORS.text}; color: {COLORS.surface}; border: 0;
    padding: 6px 8px; border-radius: 5px;
}}
QSplitter::handle {{ background: {COLORS.border}; width: 1px; }}
QScrollArea, QAbstractScrollArea, QAbstractScrollArea > QWidget > QWidget {{
    background: transparent; border: 0;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px; }}
QScrollBar::handle:vertical {{
    background: #CFC6BA; min-height: 30px; border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{ background: #B8ADA0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: none; }}

QPushButton {{
    min-height: 36px; padding: 0 14px; border-radius: 8px;
    border: 1px solid {COLORS.border}; background: {COLORS.surface};
    color: {COLORS.text}; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ background: #F6F1E9; border-color: #CBBEAD; }}
QPushButton:pressed {{ background: {COLORS.surface_secondary}; }}
QPushButton:focus {{ border: 1px solid {COLORS.accent}; }}
QPushButton:disabled {{
    background: {COLORS.disabled}; color: {COLORS.disabled_text};
    border-color: {COLORS.disabled};
}}
QPushButton[buttonRole="primary"] {{
    background: {COLORS.accent}; color: #FFFFFF; border-color: {COLORS.accent};
}}
QPushButton[buttonRole="primary"]:hover {{
    background: {COLORS.accent_hover}; border-color: {COLORS.accent_hover};
}}
QPushButton[buttonRole="primary"]:pressed {{ background: {COLORS.accent_pressed}; }}
QPushButton[buttonRole="danger"] {{
    color: {COLORS.danger}; background: transparent; border-color: transparent;
}}
QPushButton[buttonRole="danger"]:hover {{
    background: {COLORS.danger_surface}; border-color: #E4C9C5;
}}
QPushButton[buttonRole="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[buttonRole="ghost"]:hover {{ background: {COLORS.surface_secondary}; }}

QLineEdit, QPlainTextEdit {{
    background: {COLORS.surface}; border: 1px solid {COLORS.border};
    border-radius: 8px; padding: 8px 10px; selection-background-color: {COLORS.highlight};
}}
QLineEdit {{ min-height: 36px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {COLORS.accent}; }}

#meetingSidebar {{
    background: #F1ECE3; border-right: 1px solid {COLORS.border};
}}
#brandMark {{
    min-width: 42px; min-height: 42px; max-width: 42px; max-height: 42px;
    border-radius: 12px; background: {COLORS.accent}; color: #FFFFFF;
    font-size: 18px; font-weight: 700;
}}
#brandWordmark {{ font-size: 22px; font-weight: 700; color: {COLORS.text}; }}
#brandTagline {{ font-size: 11px; color: {COLORS.text_muted}; }}
#sidebarSectionTitle {{
    font-size: 11px; font-weight: 700; color: {COLORS.text_secondary};
}}
#newMeetingButton {{ min-height: 42px; text-align: right; }}
#settingsButton {{ text-align: right; }}
QListWidget {{ border: 0; background: transparent; outline: 0; }}
QListWidget::item {{
    min-height: 54px; padding: 9px 12px; margin: 2px 0;
    border-radius: 8px; color: {COLORS.text_secondary};
}}
QListWidget::item:hover {{ background: rgba(252, 250, 246, 200); color: {COLORS.text}; }}
QListWidget::item:selected {{ background: {COLORS.highlight}; color: {COLORS.text}; }}

#meetingContent {{ background: {COLORS.background}; }}
#emptyHero {{ background: transparent; }}
#emptyMark {{
    min-width: 64px; min-height: 64px; max-width: 64px; max-height: 64px;
    border-radius: 18px; background: {COLORS.highlight}; color: {COLORS.accent};
    font-size: 26px; font-weight: 700;
}}
#emptyHeroTitle {{ font-size: 24px; font-weight: 700; color: {COLORS.text}; }}
#emptyHeroText {{ font-size: 14px; color: {COLORS.text_secondary}; }}
#meetingHeader {{
    background: {COLORS.surface}; border: 1px solid {COLORS.border}; border-radius: 12px;
}}
#meetingTitle {{ font-size: 24px; font-weight: 700; color: {COLORS.text}; }}
#meetingMetadata, #meetingMetadata QLabel {{ color: {COLORS.text_secondary}; font-size: 12px; }}
#statusBadge {{
    background: {COLORS.success_surface}; color: {COLORS.success};
    border: 1px solid #D4DED2; border-radius: 7px; padding: 4px 9px;
    font-size: 12px; font-weight: 700;
}}
#statusBadge[state="warning"] {{
    background: {COLORS.warning_surface}; color: {COLORS.warning}; border-color: #E8D5B8;
}}
#statusBadge[state="error"] {{
    background: {COLORS.danger_surface}; color: {COLORS.danger}; border-color: #E4C9C5;
}}

QTabWidget::pane {{
    top: -1px; background: {COLORS.surface}; border: 1px solid {COLORS.border};
    border-radius: 11px;
}}
QTabBar::tab {{
    min-width: 98px; min-height: 40px; padding: 0 14px;
    color: {COLORS.text_secondary}; background: transparent;
    border: 0; border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {COLORS.text}; background: #F5F0E8; }}
QTabBar::tab:selected {{ color: {COLORS.accent}; border-bottom-color: {COLORS.accent}; }}

#transcriptSaveBar {{
    background: {COLORS.warning_surface}; border: 1px solid #E8D5B8; border-radius: 8px;
}}
#transcriptActionsBar QPushButton {{ min-height: 34px; padding: 0 13px; }}
#transcriptUnsavedLabel {{ color: {COLORS.warning}; font-weight: 700; }}
#transcriptSegment {{
    background: transparent; border: 0; border-bottom: 1px solid #E8E1D8;
}}
#transcriptSegment[evidenceTarget="true"] {{
    background: {COLORS.highlight}; border-right: 3px solid {COLORS.accent};
}}
#transcriptTimestamp {{ color: {COLORS.text_muted}; font-size: 11px; font-weight: 600; }}
#transcriptTextEditor {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px 3px; color: {COLORS.text}; font-size: 14px;
}}
#transcriptTextEditor:focus {{ background: {COLORS.surface}; border-color: #D4C7B6; }}

#outdatedAnalysisBanner {{
    background: {COLORS.warning_surface}; border: 1px solid #E5D1AF; border-radius: 9px;
}}
QLabel[messageType="success"] {{ color: {COLORS.success}; }}
QLabel[messageType="error"] {{ color: {COLORS.danger}; }}
QLabel[messageType="neutral"] {{ color: {COLORS.text_secondary}; }}
QProgressBar {{
    min-height: 8px; max-height: 8px; border: 0; border-radius: 4px;
    background: {COLORS.surface_secondary}; text-align: center;
}}
QProgressBar::chunk {{ background: {COLORS.accent}; border-radius: 4px; }}

#summarySurface {{
    background: {COLORS.surface}; border: 1px solid {COLORS.border}; border-radius: 11px;
}}
#analysisSectionTitle {{ font-size: 19px; font-weight: 700; color: {COLORS.text}; }}
#analysisSummary {{ font-size: 15px; color: {COLORS.text}; }}
#analysisEmptyState {{ color: {COLORS.text_muted}; font-size: 14px; }}
#analysisCard {{
    background: {COLORS.surface}; border: 1px solid {COLORS.border}; border-radius: 10px;
}}
#analysisItemTitle {{ font-size: 16px; font-weight: 700; color: {COLORS.text}; }}
#analysisItemDescription {{ font-size: 14px; color: {COLORS.text_secondary}; }}
#analysisAssignee, #analysisDeadline {{
    color: {COLORS.text_secondary}; background: {COLORS.surface_secondary};
    border-radius: 6px; padding: 4px 8px;
}}
#analysisEvidenceTitle {{ color: {COLORS.text_muted}; font-size: 11px; font-weight: 700; }}
#evidenceButton {{
    min-height: 38px; text-align: right; background: #F8F4ED;
    border: 1px solid #E6DDD1; border-radius: 7px; color: {COLORS.text_secondary};
    font-weight: 500;
}}
#evidenceButton:hover {{ background: {COLORS.highlight}; border-color: #D6C2A4; color: {COLORS.text}; }}
#missingEvidence {{ color: {COLORS.danger}; background: {COLORS.danger_surface}; }}

#dialogHeading {{ font-size: 21px; font-weight: 700; color: {COLORS.text}; }}
#dialogDescription, #sectionDescription {{ color: {COLORS.text_secondary}; font-size: 13px; }}
#filePickerSurface, #settingsSection {{
    background: {COLORS.surface}; border: 1px solid {COLORS.border}; border-radius: 10px;
}}
#settingsSectionTitle {{ font-size: 16px; font-weight: 700; color: {COLORS.text}; }}
#technicalValue {{ color: {COLORS.text_secondary}; font-size: 12px; }}
#modelStatusLabel, #credentialStatusLabel {{ font-weight: 600; }}
QDialogButtonBox QPushButton {{ min-width: 88px; }}
QMessageBox QLabel {{ min-width: 260px; }}
"""

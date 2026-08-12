"""Shared exceptions and human-friendly error mapping.

Converts low-level OCRmyPDF exceptions / exit codes into messages a
non-technical user can understand. Tracebacks are only ever shown in the
detailed log, never in the main UI.
"""
from __future__ import annotations

import traceback


class AppError(Exception):
    """Base class for application-level errors."""


class MissingDependencyError(AppError):
    """An external component (Tesseract, Ghostscript, language pack) is missing."""


class CancelError(AppError):
    """The user cancelled the current job."""


#: Maps OCRmyPDF exception types to a friendly, actionable message.
#: Keys are exception class names (imported lazily to avoid hard dependency).
_EXCEPTION_MESSAGES: dict[str, str] = {
    "MissingDependencyError": (
        "A required OCR component could not be found.\n"
        "Check the Component Status panel and install the missing program."
    ),
    "PriorOcrFoundError": (
        "This PDF already contains text.\n\n"
        "Choose \"Skip existing text\", \"Redo OCR\" or \"Force OCR\" in Advanced Settings."
    ),
    "OutputFileAccessError": (
        "The output PDF is currently open in another application.\n"
        "Close it and try again."
    ),
    "TesseractConfigError": (
        "The selected OCR language is not installed.\n"
        "Install the missing Tesseract language data to use this option."
    ),
    "EncryptedPdfError": (
        "This PDF is password-protected or encrypted.\n"
        "Remove the password first, then try again."
    ),
    "InputFileError": (
        "The PDF file could not be read. It may be corrupt or not a valid PDF."
    ),
    "DpiError": (
        "The PDF has no usable image resolution information.\n"
        "Try the \"Difficult Scan\" preset, which increases the image quality."
    ),
    "SubprocessOutputError": (
        "An OCR component failed while processing this file.\n"
        "Check the detailed log for more information."
    ),
    "BadArgsError": (
        "The requested settings cannot be combined.\n"
        "Check the options and try again."
    ),
    "UnsupportedImageFormatError": (
        "The PDF contains images in a format that cannot be processed."
    ),
    "NonEmbeddedFontsError": (
        "The PDF uses fonts that are not embedded. OCR may still be attempted."
    ),
    "FileExistsError": (
        "The output file already exists.\n"
        "Choose a different output folder or rename the existing file, then try again."
    ),
    "PermissionError": (
        "OCRmyPDF could not access a required file or folder.\n"
        "Close the PDF if it is open and check your folder permissions."
    ),
}


def error_text(exc: BaseException) -> str:
    """Return a short, safe text for an exception (no traceback)."""
    return str(exc) if str(exc) else exc.__class__.__name__


def friendly_exception_message(exc: BaseException) -> str:
    """Map an exception instance to a friendly user message."""
    cls_name = exc.__class__.__name__
    base = _EXCEPTION_MESSAGES.get(cls_name)
    if base:
        return base
    # Fall back to the raw message, which is usually still readable.
    text = error_text(exc)
    return text or f"An unexpected error occurred ({cls_name})."


def exit_code_message(exit_code: int) -> str:
    """Map an OCRmyPDF exit code to a friendly message (fallback path)."""
    from ocrmypdf import ExitCode

    codes: dict[int, str] = {
        ExitCode.bad_args: "Invalid settings for this file.",
        ExitCode.input_file: "The PDF file could not be read. It may be corrupt or not a valid PDF.",
        ExitCode.missing_dependency: "A required OCR component could not be found.",
        ExitCode.invalid_output_pdf: "The output PDF could not be created from this input.",
        ExitCode.file_access_error: "Could not write the output file. It may be open in another application.",
        ExitCode.already_done_ocr: "This PDF already contains text.",
        ExitCode.child_process_error: "An OCR component failed while processing this file.",
        ExitCode.encrypted_pdf: "This PDF is password-protected or encrypted.",
        ExitCode.invalid_config: "Invalid configuration for this file.",
        ExitCode.pdfa_conversion_failed: "PDF/A conversion failed for this file.",
        ExitCode.other_error: "An unexpected error occurred while processing this file.",
        ExitCode.ctrl_c: "The operation was cancelled.",
    }
    return codes.get(exit_code, f"OCR processing failed (exit code {exit_code}).")


def format_traceback(exc: BaseException) -> str:
    """Return the full traceback text (for the detailed log only)."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

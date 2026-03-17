import json
from pathlib import Path
import warnings


UNSET = object()


def normalize_save_flag(save_file):
    if isinstance(save_file, bool):
        return save_file

    value = str(save_file).strip().lower()
    if value in {"y", "yes", "true", "1"}:
        return True
    if value in {"n", "no", "false", "0"}:
        return False
    raise ValueError("save_file must be one of y/n/true/false")


def resolve_save_enabled(save, save_file=UNSET, default=True):
    if save is not None:
        return bool(save)

    if save_file is not UNSET:
        warnings.warn(
            "`save_file` is deprecated; use `save` instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        return normalize_save_flag(save_file)

    return default


def resolve_output_path(output_path=None, output_dir=None, default_filename=None):
    if output_path:
        return Path(output_path).expanduser()
    if output_dir is None or default_filename is None:
        raise ValueError("Saving requires output_path or output_dir")
    return Path(output_dir).expanduser() / default_filename


def ensure_parent_dir(path):
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_json(payload, path):
    target = ensure_parent_dir(path)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return target


def write_dataframe_csv(dataframe, path):
    target = ensure_parent_dir(path)
    dataframe.to_csv(target, index=False)
    return target

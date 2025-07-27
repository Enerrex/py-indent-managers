from typing import Any, Dict, List, Optional, Tuple, Type, Union, get_origin, get_args
from dataclasses import dataclass
import os
import json
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo as PydanticFieldInfo, PydanticUndefined
from sqlmodel import SQLModel, Field, create_engine, Session

@dataclass
class ConflictField:
    field_type: str
    required: bool

@dataclass
class MergeReport:
    field_name: str
    issue: str
    models: Dict[str, ConflictField]

class PayloadMergeError(Exception):
    """Raised when one or more merge conflicts are detected."""
    pass


def prettify_type(tp: Any) -> str:
    """
    Simplify type annotations to a user-friendly string:
    - Unwrap Optional[T] to T
    - Represent Union types as 'A or B'
    - Strip 'typing.' prefixes
    - Use __name__ when available
    """
    origin = get_origin(tp)
    if origin is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return prettify_type(args[0])
        return " or ".join(prettify_type(a) for a in args)
    if hasattr(tp, "__name__"):
        return tp.__name__
    return str(tp).replace("typing.", "")


def merge_payloads(
    *,
    subpayloads: List[Type[SQLModel]],
    specpayloads: List[Type[BaseModel]],
    core_name: str = "CorePayload",
    table_name: str = "core_payload",
) -> Type[SQLModel]:
    spec_names = {sp.__name__ for sp in specpayloads}
    reports: List[MergeReport] = []
    fields: Dict[str, List[Tuple[Any, bool, Any, str]]] = {}

    # Collect field definitions
    for cls in (*subpayloads, *specpayloads):
        src = cls.__name__
        if hasattr(cls, "model_fields"):  # Pydantic v2
            for name, info in cls.model_fields.items():
                fields.setdefault(name, []).append((info.annotation, info.is_required(), info, src))
        elif hasattr(cls, "__fields__"):  # Pydantic v1
            for name, mf in cls.__fields__.items():
                fields.setdefault(name, []).append((mf.outer_type_, mf.required, mf.field_info, src))

    core_fields: Dict[str, Tuple[Any, Any]] = {}
    # Analyze for conflicts and prepare core fields
    for name, defs in fields.items():
        base_types, made_optional = [], []
        spec_requires = False
        for raw, required_flag, info, src in defs:
            origin = get_origin(raw)
            if origin is Union and type(None) in get_args(raw):
                args = [a for a in get_args(raw) if a is not type(None)]
                base = args[0] if len(args) == 1 else raw
                base_types.append(base)
                made_optional.append(True)
            else:
                base_types.append(raw)
                made_optional.append(False)
            if src in spec_names and required_flag:
                spec_requires = True

        # Report type mismatch across any two models
        if len({*base_types}) > 1:
            reports.append(
                MergeReport(
                    field_name=name,
                    issue="type_mismatch",
                    models={
                        model_src: ConflictField(
                            field_type=prettify_type(raw_type),
                            required=required_flag
                        ) for raw_type, required_flag, _, model_src in defs
                    }
                )
            )
            continue
        # Report spec violation when an Optional in sub conflicts with required in spec
        bad_subs = [defs[i][3] for i, opt in enumerate(made_optional)
                    if opt and defs[i][3] not in spec_names]
        if spec_requires and bad_subs:
            reports.append(
                MergeReport(
                    field_name=name,
                    issue="spec_violation",
                    models={
                        model_src: ConflictField(
                            field_type=prettify_type(raw_type),
                            required=required_flag
                        ) for raw_type, required_flag, _, model_src in defs
                    }
                )
            )
            continue

        # Build core field metadata
        final_optional = bool(bad_subs) and not spec_requires
        chosen_info = next((info for *_, info, src in defs if src in spec_names), defs[0][2])
        if hasattr(chosen_info, "default"):
            default = chosen_info.default if chosen_info.default is not PydanticUndefined else ...
        else:
            default = ... if chosen_info.is_required() else None
        extras: Dict[str, Any] = {}
        if hasattr(chosen_info, "metadata"):
            for k, v in getattr(chosen_info, "metadata") or []:
                extras[k] = v
        raw_type = defs[0][0]
        final_type = get_args(raw_type)[0] if final_optional and get_origin(raw_type) is Union else raw_type
        ann = Optional[final_type] if final_optional else final_type
        core_fields[name] = (ann, Field(default, **extras))

    # Abort on any conflicts
    if reports:
        message = "Merge conflicts detected:\n"
        for r in reports:
            message += f"- {r.issue} on '{r.field_name}': {r.models}\n"
        raise PayloadMergeError(message)

    # Create CorePayload
    CorePayload = create_model(
        core_name,
        __base__=SQLModel,
        __module__=__name__,
        __config__={"orm_mode": True},
        __tablename__=table_name,
        **core_fields,
    )
    return CorePayload


def payload_model_to_json(
    cls: Type[SQLModel] or Type[BaseModel],
    fields_data: Dict[str, List[Tuple[Any, bool, Any, str]]],
    reports: List[MergeReport]
) -> Dict[str, Any]:
    definition: Dict[str, Any] = {}
    if hasattr(cls, "model_fields"):  # Pydantic v2
        for name, info in cls.model_fields.items():
            definition[name] = {
                "type": prettify_type(info.annotation),
                "required": info.is_required(),
                "default": None if info.default is PydanticUndefined else info.default,
            }
    elif hasattr(cls, "__fields__"):  # Pydantic v1
        for name, mf in cls.__fields__.items():
            definition[name] = {
                "type": prettify_type(mf.outer_type_),
                "required": mf.required,
                "default": mf.default,
            }
    conflicts: List[Dict[str, Any]] = []
    for r in reports:
        if cls.__name__ in r.models:
            conflicts.append({
                "field_name": r.field_name,
                "issue": r.issue,
                "models": {
                    k: {"field_type": v.field_type, "required": v.required}
                    for k, v in r.models.items()
                },
            })
    return {"definition": definition, "conflicts": conflicts}


def generate_payload_reports(
    subpayloads: List[Type[SQLModel]],
    specpayloads: List[Type[BaseModel]]
) -> Dict[str, Dict[str, Any]]:
    spec_names = {sp.__name__ for sp in specpayloads}
    reports: List[MergeReport] = []
    fields: Dict[str, List[Tuple[Any, bool, Any, str]]] = {}

    for cls in (*subpayloads, *specpayloads):
        src = cls.__name__
        if hasattr(cls, "model_fields"):  # Pydantic v2
            for name, info in cls.model_fields.items():
                fields.setdefault(name, []).append((info.annotation, info.is_required(), info, src))
        elif hasattr(cls, "__fields__"):  # Pydantic v1
            for name, mf in cls.__fields__.items():
                fields.setdefault(name, []).append((mf.outer_type_, mf.required, mf.field_info, src))

    for name, defs in fields.items():
        base_types, made_optional = [], []
        spec_requires = False
        for raw, required_flag, info, src in defs:
            origin = get_origin(raw)
            if origin is Union and type(None) in get_args(raw):
                args = [a for a in get_args(raw) if a is not type(None)]
                base = args[0] if len(args) == 1 else raw
                base_types.append(base)
                made_optional.append(True)
            else:
                base_types.append(raw)
                made_optional.append(False)
            if src in spec_names and required_flag:
                spec_requires = True
        if len({*base_types}) > 1:
            reports.append(
                MergeReport(
                    field_name=name,
                    issue="type_mismatch",
                    models={
                        model_src: ConflictField(
                            field_type=prettify_type(raw_type),
                            required=required_flag
                        ) for raw_type, required_flag, _, model_src in defs
                    }
                )
            )
            continue
        bad_subs = [defs[i][3] for i, opt in enumerate(made_optional) if opt and defs[i][3] not in spec_names]
        if spec_requires and bad_subs:
            reports.append(
                MergeReport(
                    field_name=name,
                    issue="spec_violation",
                    models={
                        model_src: ConflictField(
                            field_type=prettify_type(raw_type),
                            required=required_flag
                        ) for raw_type, required_flag, _, model_src in defs
                    }
                )
            )

    report_map: Dict[str, Dict[str, Any]] = {}
    for cls in (*subpayloads, *specpayloads):
        report_map[cls.__name__] = payload_model_to_json(cls, fields, reports)

    return report_map


def write_reports_to_files(
    report_map: Dict[str, Dict[str, Any]],
    output_dir: str = "reports"
) -> None:
    """
    Dump each payload report to JSON file in the specified directory.
    File names match the model name (e.g. UserNamePayload.json).
    """
    os.makedirs(output_dir, exist_ok=True)
    for model_name, data in report_map.items():
        path = os.path.join(output_dir, f"{model_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

# Example usage:
if __name__ == "__main__":
    from sqlmodel import Field
    from typing import Optional

    class UserNamePayload(SQLModel):
        first_name: str
        last_name: str

    class ContactPayload(SQLModel):
        email: Optional[str] = None
        phone: Optional[str] = None

    class RequiredUserFields(BaseModel):
        email: str

    # Generate and write JSON reports
    reports = generate_payload_reports(
        subpayloads=[UserNamePayload, ContactPayload],
        specpayloads=[RequiredUserFields]
    )
    write_reports_to_files(reports, output_dir="reports")
    print(f"Reports written to '{os.path.abspath('reports')}'")

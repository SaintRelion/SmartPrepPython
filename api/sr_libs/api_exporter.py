import json
import inspect
from typing import Dict, get_type_hints, get_origin, get_args, List, Union, Any

# Controllers
from api.auth.router import AuthController
from api.slots.router import SlotsController
from api.exam.router import ExamController
from api.analytics.router import AnalyticsController

CONTROLLERS = {
    "Auth": AuthController,
    "Slots": SlotsController,
    "Exam": ExamController,
    "Analytics": AnalyticsController,
}


def get_type_name(t: Any) -> str:
    """Standardizes Python types to names the SR_Resolver map understands."""
    origin = get_origin(t)

    # 1. Handle Dictionaries
    if origin in [dict, Dict]:
        args = get_args(t)
        if args and len(args) == 2:
            k = get_type_name(args[0])
            v = get_type_name(args[1])
            return f"Dict[{k}, {v}]"
        return "dict"

    # 2. Get the actual name
    name = getattr(t, "__name__", str(t)).lower()

    # FIX: Use EXACT matching for primitives so "Point" isn't caught as "int"
    if name == "int":
        return "int"
    if name in ["str", "string"]:
        return "string"
    if name == "float":
        return "float"
    if name == "bool":
        return "bool"
    if "datetime" in name:
        return "datetime"

    # 3. If it's a custom class (like SlotHistoryPoint), return its real name
    return getattr(t, "__name__", "Object")


def register_model_recursive(spec: dict, model_cls: Any):
    if not hasattr(model_cls, "model_fields"):
        return
    m_name = model_cls.__name__
    if m_name in spec["models"]:
        return

    spec["models"][m_name] = {}
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        origin = get_origin(annotation)

        # Structure Detection
        is_list = origin in [list, List]
        is_dict = origin in [dict, Dict]

        inner_type = annotation

        # Unwrap for recursion
        if is_list:
            inner_type = get_args(annotation)[0]
        elif is_dict:
            inner_type = get_args(annotation)[1]  # Recurse into the Value type

        # Handle Optional/Union
        if get_origin(inner_type) is Union:
            args = get_args(inner_type)
            inner_type = [t for t in args if t is not type(None)][0]
            # Secondary check for nested structures inside Optional
            inner_origin = get_origin(inner_type)
            if inner_origin in [list, List]:
                is_list = True
            if inner_origin in [dict, Dict]:
                is_dict = True

        spec["models"][m_name][name] = {
            "type": get_type_name(
                annotation if not (is_list or is_dict) else inner_type
            ),
            "is_list": is_list,
            "is_dict": is_dict,
            # Extra metadata for the dict_template
            "raw_annotation": str(annotation),
        }

        if hasattr(inner_type, "model_fields"):
            register_model_recursive(spec, inner_type)


def build_sr_spec():
    spec = {"models": {}, "repositories": {}}
    ALLOWED_SUFFIXES = ("_GET", "_POST", "_DELETE", "_PATCH")

    for repo_name, ctrl_cls in CONTROLLERS.items():
        spec["repositories"][repo_name] = []
        methods = inspect.getmembers(ctrl_cls, predicate=inspect.isfunction)

        for method_name, func in methods:
            if method_name.startswith("_"):
                continue

            if not method_name.endswith(ALLOWED_SUFFIXES):
                raise ValueError(f"❌ CONVENTION VIOLATION: {method_name}")

            # Method Determination
            suffix_map = {
                "_GET": "GET",
                "_POST": "POST",
                "_DELETE": "DELETE",
                "_PATCH": "PATCH",
            }
            http_method = next(
                v for k, v in suffix_map.items() if method_name.endswith(k)
            )
            clean_name = method_name[: method_name.rfind("_")]

            # --- RESOLVE MODELS ---
            hints = get_type_hints(func)
            sig = inspect.signature(func)
            api_params = [
                p
                for p in sig.parameters.values()
                if p.name not in ["db", "current_user", "self"]
            ]

            req_model_name = "None"
            actual_req = None
            if api_params:
                req_type = api_params[0].annotation
                actual_req = (
                    get_args(req_type)[0]
                    if get_origin(req_type) in [list, List]
                    else req_type
                )
                req_model_name = getattr(actual_req, "__name__", "Object")
                register_model_recursive(spec, actual_req)

            # --- RESOLVE RESPONSE ---
            res_type = hints.get("return", object)
            res_origin = get_origin(res_type)
            res_is_list = res_origin in [list, List]
            res_is_dict = res_origin in [dict, Dict]

            actual_res = res_type
            if res_is_list:
                actual_res = get_args(res_type)[0]
            elif res_is_dict:
                actual_res = get_args(res_type)[1]

            res_name = getattr(actual_res, "__name__", "Object")
            register_model_recursive(spec, actual_res)

            # --- FILE DETECTION ---
            is_file = any(
                "UploadFile" in str(p.annotation) for p in sig.parameters.values()
            )
            if not is_file and actual_req and hasattr(actual_req, "model_fields"):
                is_file = any(
                    "UploadFile" in str(f.annotation)
                    for f in actual_req.model_fields.values()
                )

            spec["repositories"][repo_name].append(
                {
                    "name": clean_name,
                    "path": f"{repo_name.lower()}/{clean_name}",
                    "method": http_method,
                    "request_model": req_model_name,
                    "response_model": res_name,
                    "res_is_list": res_is_list,
                    "res_is_dict": res_is_dict,  # Macro-level dict detection
                    "is_file_upload": is_file,
                }
            )

    return spec


def register_model_recursive(spec: dict, model_cls: Any):
    if not hasattr(model_cls, "model_fields"):
        return
    m_name = model_cls.__name__
    if m_name in spec["models"]:
        return

    spec["models"][m_name] = {}
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation

        # 1. Detect if it is a List at the field level
        origin = get_origin(annotation)
        is_list = origin in [list, List]

        # 2. Unwrap List/Optional/Union to get the core type
        inner_type = annotation
        if is_list:
            inner_type = get_args(annotation)[0]

        # Handle Optional (Union[T, None])
        if get_origin(inner_type) is Union:
            args = get_args(inner_type)
            inner_type = [t for t in args if t is not type(None)][0]
            # Re-check list if it was Optional[List[int]]
            if get_origin(inner_type) in [list, List]:
                is_list = True
                inner_type = get_args(inner_type)[0]

        spec["models"][m_name][name] = {
            "type": get_type_name(inner_type),
            "is_list": is_list,
        }

        # 3. Recurse if the inner type is another Pydantic model
        if hasattr(inner_type, "model_fields"):
            register_model_recursive(spec, inner_type)


def build_sr_spec():
    spec = {"models": {}, "repositories": {}}

    # Protocol Enforcement
    ALLOWED_SUFFIXES = ("_GET", "_POST", "_DELETE", "_PATCH")

    for repo_name, ctrl_cls in CONTROLLERS.items():
        spec["repositories"][repo_name] = []
        methods = inspect.getmembers(ctrl_cls, predicate=inspect.isfunction)

        for method_name, func in methods:
            if method_name.startswith("_"):
                continue

            # --- CONVENTION CHECK ---
            if not method_name.endswith(ALLOWED_SUFFIXES):
                raise ValueError(
                    f"❌ CONVENTION VIOLATION: Method '{method_name}' in '{repo_name}' "
                    f"must end with one of {ALLOWED_SUFFIXES}. "
                    f"Example: '{method_name}_GET' or '{method_name}_POST'."
                )

            # Determine Method and Clean Name for SDK/URL
            if method_name.endswith("_GET"):
                http_method = "GET"
                clean_name = method_name[:-4]
            elif method_name.endswith("_POST"):
                http_method = "POST"
                clean_name = method_name[:-5]
            elif method_name.endswith("_DELETE"):
                http_method = "DELETE"
                clean_name = method_name[:-7]
            elif method_name.endswith("_PATCH"):
                http_method = "PATCH"
                clean_name = method_name[:-6]

            # --- RESOLVE MODELS ---
            hints = get_type_hints(func)
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            api_params = [
                p for p in params if p.name not in ["db", "current_user", "self"]
            ]

            req_model_name = None
            actual_req = None
            if api_params:
                req_type = api_params[0].annotation
                # Handle direct List[Model] as request body
                if get_origin(req_type) in [list, List]:
                    actual_req = get_args(req_type)[0]
                else:
                    actual_req = req_type

                req_model_name = getattr(actual_req, "__name__", "Object")
                register_model_recursive(spec, actual_req)

            # --- RESOLVE RESPONSE ---
            res_type = hints.get("return", object)
            res_is_list = get_origin(res_type) in [list, List]
            actual_res = get_args(res_type)[0] if res_is_list else res_type
            res_name = getattr(actual_res, "__name__", "Object")
            register_model_recursive(spec, actual_res)

            # --- DUAL-LAYER FILE DETECTION ---
            is_file = False
            for p in params:
                if "UploadFile" in str(p.annotation):
                    is_file = True
                    break

            if not is_file and actual_req and hasattr(actual_req, "model_fields"):
                for _, f_info in actual_req.model_fields.items():
                    if "UploadFile" in str(f_info.annotation):
                        is_file = True
                        break

            # --- BUILD REPO ENTRY ---
            spec["repositories"][repo_name].append(
                {
                    "name": clean_name,
                    "path": f"{repo_name.lower()}/{clean_name}",
                    "method": http_method,
                    "request_model": req_model_name,
                    "response_model": res_name,
                    "res_is_list": res_is_list,
                    "is_file_upload": is_file,
                }
            )

    return spec

# -------------------------------------------------------------------------------
#   Generate Zig bindings.
#
#   Zig coding style:
#   - types are PascalCase
#   - functions are snake_case
#   - otherwise snake_case
# -------------------------------------------------------------------------------
import gen_ir
import os, shutil, sys

import gen_util as util

bindings_root = "sokol-v/src"
c_root = f"{bindings_root}/sokol/c"
module_root = f"{bindings_root}/sokol"


# module_names = {
#     "slog_": "sv_log",
#     "sg_": "sv_gfx",
#     "sapp_": "sv_app",
#     "stm_": "sv_time",
#     "saudio_": "sv_audio",
#     "sgl_": "sv_gl",
#     "sdtx_": "sv_debugtext",
#     "sshape_": "sv_shape",
#     "sglue_": "sv_glue",
#     "sfetch_": "sv_fetch",
#     "simgui_": "sv_imgui",
# }

module_names = {
    "slog_": "svlog",
    "sg_": "svg",
    "sapp_": "svapp",
    "stm_": "svtm",
    "saudio_": "svaudio",
    "sgl_": "svgl",
    "sdtx_": "svdtx",
    "sshape_": "svshape",
    "sglue_": "svglue",
    "sfetch_": "svfetch",
    "simgui_": "svimgui",
}

c_source_paths = {
    "slog_": "sokol-v/src/sokol/c/sokol_log.c",
    "sg_": "sokol-v/src/sokol/c/sokol_gfx.c",
    "sapp_": "sokol-v/src/sokol/c/sokol_app.c",
    "stm_": "sokol-v/src/sokol/c/sokol_time.c",
    "saudio_": "sokol-v/src/sokol/c/sokol_audio.c",
    "sgl_": "sokol-v/src/sokol/c/sokol_gl.c",
    "sdtx_": "sokol-v/src/sokol/c/sokol_debugtext.c",
    "sshape_": "sokol-v/src/sokol/c/sokol_shape.c",
    "sglue_": "sokol-v/src/sokol/c/sokol_glue.c",
    "sfetch_": "sokol-v/src/sokol/c/sokol_fetch.c",
    "simgui_": "sokol-v/src/sokol/c/sokol_imgui.c",
}

ignores = [
    "sdtx_printf",
    "sdtx_vprintf",
    "sg_install_trace_hooks",
    "sg_trace_hooks",
]

# functions that need to be exposed as 'raw' C callbacks without a Zig wrapper function
c_callbacks = ["slog_func"]

# NOTE: syntax for function results: "func_name.RESULT"
overrides = {
    "sgl_error": "sgl_get_error",  # 'error' is reserved in Zig
    "sgl_deg": "sgl_as_degrees",
    "sgl_rad": "sgl_as_radians",
    "sg_apply_uniforms.ub_slot": "uint32_t",
    "sg_draw.base_element": "uint32_t",
    "sg_draw.num_elements": "uint32_t",
    "sg_draw.num_instances": "uint32_t",
    "sshape_element_range_t.base_element": "uint32_t",
    "sshape_element_range_t.num_elements": "uint32_t",
    "sdtx_font.font_index": "uint32_t",
    "SGL_NO_ERROR": "SGL_ERROR_NO_ERROR",
    "sfetch_continue": "continue_fetching",  # 'continue' is reserved in Zig
    "sfetch_desc": "sfetch_get_desc",  # 'desc' shadowed by earlier definition
}

prim_types = {
    "int": "int",
    "bool": "bool",
    "char": "u8",
    "int8_t": "i8",
    "uint8_t": "u8",
    "int16_t": "i16",
    "uint16_t": "u16",
    "int32_t": "int",
    "uint32_t": "u32",
    "int64_t": "i64",
    "uint64_t": "u64",
    "float": "f32",
    "double": "f64",
    "uintptr_t": "usize",
    "intptr_t": "isize",
    "size_t": "usize",
}

prim_defaults = {
    "int": "0",
    "bool": "false",
    "int8_t": "0",
    "uint8_t": "0",
    "int16_t": "0",
    "uint16_t": "0",
    "int32_t": "0",
    "uint32_t": "0",
    "int64_t": "0",
    "uint64_t": "0",
    "float": "0.0",
    "double": "0.0",
    "uintptr_t": "0",
    "intptr_t": "0",
    "size_t": "0",
}

keywords = """
shared lock continue
""".split()


struct_types = []
enum_types = []
enum_items = {}
out_lines = ""


def reset_globals():
    global struct_types
    global enum_types
    global enum_items
    global out_lines
    struct_types = []
    enum_types = []
    enum_items = {}
    out_lines = ""


def get_v_module_path(c_prefix):
    return f"{module_root}/{module_names[c_prefix]}"


def make_v_module_directory(c_prefix):
    path = get_v_module_path(c_prefix)
    if not os.path.isdir(path):
        os.makedirs(path)


def l(s):
    global out_lines
    out_lines += s + "\n"


def wrap_keywords(s):
    if s in keywords:
        return f"_{s}"
    else:
        return s


def as_zig_prim_type(s):
    return prim_types[s]


# prefix_bla_blub(_t) => (dep.)BlaBlub
def as_zig_struct_type(s, prefix):
    parts = s.lower().split("_")
    outp = "" if s.startswith(prefix) else f"{parts[0]}."
    for part in parts[1:]:
        # ignore '_t' type postfix
        if part != "t":
            outp += part.capitalize()
    return outp


# prefix_bla_blub(_t) => (dep.)BlaBlub
def as_zig_enum_type(s, prefix, wrap=True):
    parts = s.lower().split("_")
    outp = "" if s.startswith(prefix) else f"{parts[0]}."
    for part in parts[1:]:
        if part != "t":
            outp += part.capitalize()
    if wrap:
        outp = wrap_keywords(outp)
    return outp


def check_override(name, default=None):
    if name in overrides:
        return overrides[name]
    elif default is None:
        return name
    else:
        return default


def check_ignore(name):
    return name in ignores


# PREFIX_BLA_BLUB to bla_blub
def as_lower_snake_case(s, prefix, wrap=True):
    outp = s.lower()
    if outp.startswith(prefix):
        outp = outp[len(prefix) :]
    if wrap:
        outp = wrap_keywords(outp)
    return outp


# PREFIX_ENUM_BLA => Bla, _PREFIX_ENUM_BLA => Bla
def as_enum_item_name(s, wrap=True):
    outp = s.lstrip("_")
    parts = outp.split("_")[2:]
    outp = "_".join(parts)
    if outp[0].isdigit():
        outp = "_" + outp
    return as_lower_snake_case(outp, "")


def enum_default_item(enum_name):
    return enum_items[enum_name][0]


def is_prim_type(s):
    return s in prim_types


def is_struct_type(s):
    return s in struct_types


def is_enum_type(s):
    return s in enum_types


def is_const_prim_ptr(s):
    for prim_type in prim_types:
        if s == f"const {prim_type} *":
            return True
    return False


def is_prim_ptr(s):
    for prim_type in prim_types:
        if s == f"{prim_type} *":
            return True
    return False


def is_const_struct_ptr(s):
    for struct_type in struct_types:
        if s == f"const {struct_type} *":
            return True
    return False


def type_default_value(s):
    return prim_defaults[s]


def as_c_arg_type(arg_type, prefix):
    if arg_type == "void":
        return ""
    elif is_prim_type(arg_type):
        return as_zig_prim_type(arg_type)
    elif is_struct_type(arg_type):
        return as_zig_struct_type(arg_type, prefix)
    elif is_enum_type(arg_type):
        return as_zig_enum_type(arg_type, prefix)
    elif util.is_void_ptr(arg_type):
        return "voidptr"
    elif util.is_const_void_ptr(arg_type):
        return "voidptr"
    elif util.is_string_ptr(arg_type):
        return "&u8"
    elif is_const_struct_ptr(arg_type):
        return f"&{as_zig_struct_type(util.extract_ptr_type(arg_type), prefix)}"
    elif is_prim_ptr(arg_type):
        return f"&{as_zig_prim_type(util.extract_ptr_type(arg_type))}"
    elif is_const_prim_ptr(arg_type):
        return f"&{as_zig_prim_type(util.extract_ptr_type(arg_type))}"
    else:
        sys.exit(f"Error as_c_arg_type(): {arg_type}")


def as_zig_arg_type(arg_prefix, arg_type, prefix):
    # NOTE: if arg_prefix is None, the result is used as return value
    pre = "" if arg_prefix is None else arg_prefix
    if arg_type == "void":
        if arg_prefix is None:
            return "void"
        else:
            return ""
    elif is_prim_type(arg_type):
        return pre + as_zig_prim_type(arg_type)
    elif is_struct_type(arg_type):
        return pre + as_zig_struct_type(arg_type, prefix)
    elif is_enum_type(arg_type):
        return pre + as_zig_enum_type(arg_type, prefix)
    elif util.is_void_ptr(arg_type):
        return pre + "voidptr"
    elif util.is_const_void_ptr(arg_type):
        return pre + "voidptr"
    elif util.is_string_ptr(arg_type):
        return pre + "string"
    elif is_const_struct_ptr(arg_type):
        # not a bug, pass const structs by value
        return pre + f"&{as_zig_struct_type(util.extract_ptr_type(arg_type), prefix)}"
    elif is_prim_ptr(arg_type):
        return pre + f"&{as_zig_prim_type(util.extract_ptr_type(arg_type))}"
    elif is_const_prim_ptr(arg_type):
        return pre + f"&{as_zig_prim_type(util.extract_ptr_type(arg_type))}"
    else:
        sys.exit(f"ERROR as_zig_arg_type(): {arg_type}")


def is_zig_string(zig_type):
    return zig_type == "string"


# get C-style arguments of a function pointer as string
def funcptr_args_c(field_type, prefix):
    tokens = field_type[field_type.index("(*)") + 4 : -1].split(",")
    s = ""
    for token in tokens:
        arg_type = token.strip()
        if s != "":
            s += ", "
        c_arg = as_c_arg_type(arg_type, prefix)
        if c_arg == "void":
            return "voidptr"
        else:
            s += c_arg
    return s


# get C-style result of a function pointer as string
def funcptr_result_c(field_type):
    res_type = field_type[: field_type.index("(*)")].strip()
    if res_type == "void":
        return ""
    elif is_prim_type(res_type):
        return as_zig_prim_type(res_type)
    elif util.is_const_void_ptr(res_type):
        return "voidptr"
    elif util.is_void_ptr(res_type):
        return "voidptr"
    else:
        sys.exit(f"ERROR funcptr_result_c(): {field_type}")


def funcdecl_args_c(decl, prefix):
    s = ""
    func_name = decl["name"]
    for param_decl in decl["params"]:
        if s != "":
            s += ", "
        param_name = param_decl["name"]
        param_type = check_override(
            f"{func_name}.{param_name}", default=param_decl["type"]
        )
        s += as_c_arg_type(param_type, prefix)
    return s


def funcdecl_args_zig(decl, prefix):
    s = ""
    func_name = decl["name"]
    for param_decl in decl["params"]:
        if s != "":
            s += ", "
        param_name = param_decl["name"]
        param_type = check_override(
            f"{func_name}.{param_name}", default=param_decl["type"]
        )
        s += f"{as_zig_arg_type(f'{wrap_keywords(param_name)} ', param_type, prefix)}"
    return s


def funcdecl_result_c(decl, prefix):
    func_name = decl["name"]
    decl_type = decl["type"]
    result_type = check_override(
        f"{func_name}.RESULT", default=decl_type[: decl_type.index("(")].strip()
    )
    return as_c_arg_type(result_type, prefix)


def funcdecl_result_zig(decl, prefix):
    func_name = decl["name"]
    decl_type = decl["type"]
    result_type = check_override(
        f"{func_name}.RESULT", default=decl_type[: decl_type.index("(")].strip()
    )
    zig_res_type = as_zig_arg_type(None, result_type, prefix)
    return zig_res_type


def gen_struct(decl, prefix):
    struct_name = check_override(decl["name"])
    # zig_type = as_zig_struct_type(struct_name, prefix)
    l(f"pub struct C.{struct_name} {{")
    l(f"pub mut:")
    for field in decl["fields"]:
        field_name = check_override(field["name"])
        field_type = check_override(
            f"{struct_name}.{field_name}", default=field["type"]
        )
        if field_name.startswith("_"):
            # field_name = f"internal_{field_name[1:]}"
            continue
        if is_prim_type(field_type):
            if (
                type_default_value(field_type) == "0"
                or type_default_value(field_type) == "false"
            ):
                l(f"    {field_name} {as_zig_prim_type(field_type)}")
            else:
                l(
                    f"    {field_name} {as_zig_prim_type(field_type)} = {type_default_value(field_type)}"
                )
        elif is_struct_type(field_type):
            l(f"    {field_name} {as_zig_struct_type(field_type, prefix)}")
        elif is_enum_type(field_type):
            l(
                f"    {field_name} {as_zig_enum_type(field_type, prefix)} = .{enum_default_item(field_type)}"
            )
        elif util.is_string_ptr(field_type):
            l(f"    {field_name} &u8 = unsafe {{ nil }}")
        elif util.is_const_void_ptr(field_type):
            l(f"    {field_name}  voidptr")
        elif util.is_void_ptr(field_type):
            l(f"    {field_name}  voidptr")
        elif is_const_prim_ptr(field_type):
            l(
                f"    {field_name}  &{as_zig_prim_type(util.extract_ptr_type(field_type))}"
            )
        elif util.is_func_ptr(field_type):
            l(
                f"    {field_name}  fn ({funcptr_args_c(field_type, prefix)}) {funcptr_result_c(field_type)} = unsafe {{ nil }}"
            )
        elif util.is_1d_array_type(field_type):
            array_type = util.extract_array_type(field_type)
            array_sizes = util.extract_array_sizes(field_type)
            if is_prim_type(array_type) or is_struct_type(array_type):
                if is_prim_type(array_type):
                    zig_type = as_zig_prim_type(array_type)
                    def_val = type_default_value(array_type)
                elif is_struct_type(array_type):
                    zig_type = as_zig_struct_type(array_type, prefix)
                    def_val = ""
                elif is_enum_type(array_type):
                    zig_type = as_zig_enum_type(array_type, prefix)
                    def_val = ""
                else:
                    sys.exit(f"ERROR gen_struct is_1d_array_type: {array_type}")
                t0 = f"[{array_sizes[0]}]{zig_type}"
                t1 = f"[{array_sizes[0]}]{zig_type}"
                # TODO: , init: {def_val}
                l(f"    {field_name} {t0} = {t1}{{}}")
            elif util.is_const_void_ptr(array_type):
                # TODO: , init: null
                l(
                    f"    {field_name} [{array_sizes[0]}]voidptr = [{array_sizes[0]}]voidptr{{}}"
                )
            else:
                sys.exit(
                    f"ERROR gen_struct: array {field_name}: {field_type} => {array_type} [{array_sizes[0]}]"
                )
        elif util.is_2d_array_type(field_type):
            array_type = util.extract_array_type(field_type)
            array_sizes = util.extract_array_sizes(field_type)
            if is_prim_type(array_type):
                zig_type = as_zig_prim_type(array_type)
                def_val = type_default_value(array_type)
            elif is_struct_type(array_type):
                zig_type = as_zig_struct_type(array_type, prefix)
                def_val = f"{zig_type}{{}}"
            else:
                sys.exit(f"ERROR gen_struct is_2d_array_type: {array_type}")
            t0 = f"[{array_sizes[0]}][{array_sizes[1]}]{zig_type}"
            l(
                f"    {field_name} {t0} = [{array_sizes[0]}][{array_sizes[1]}]{zig_type}{{init: [{array_sizes[1]}]{zig_type}{{init: {def_val}}}}}"
            )
        else:
            sys.exit(f"ERROR gen_struct: {field_name}: {field_type}")
    l("}")
    zig_type = as_zig_struct_type(struct_name, prefix)
    l(f"pub type {zig_type} = C.{struct_name}")
    l("")


def gen_consts(decl, prefix):
    for item in decl["items"]:
        item_name = check_override(item["name"])
        l(f"pub const {util.as_lower_snake_case(item_name, prefix)} = {item['value']}")


def gen_enum(decl, prefix):
    enum_name = check_override(decl["name"])
    l(f"pub enum {as_zig_enum_type(enum_name, prefix)} as u32 {{")
    for item in decl["items"]:
        item_name = as_enum_item_name(check_override(item["name"]))
        if item_name != "force_u32":
            if "value" in item:
                l(f"    {item_name} = {item['value']}")
            else:
                l(f"    {item_name}")
    l("}")


def gen_func_c(decl, prefix):
    l(
        f"fn C.{decl['name']}({funcdecl_args_c(decl, prefix)}) {funcdecl_result_c(decl, prefix)}"
    )


def gen_func_zig(decl, prefix):
    c_func_name = decl["name"]
    zig_func_name = as_lower_snake_case(check_override(decl["name"]), prefix)
    if c_func_name in c_callbacks:
        # a simple forwarded C callback function
        l(f"pub const {zig_func_name} = {c_func_name}")
    else:
        zig_res_type = funcdecl_result_zig(decl, prefix)
        if zig_res_type == "void":
            l(f"pub fn {zig_func_name}({funcdecl_args_zig(decl, prefix)}) {{")
        else:
            l(
                f"pub fn {zig_func_name}({funcdecl_args_zig(decl, prefix)}) {zig_res_type} {{"
            )
        if is_zig_string(zig_res_type):
            # special case: convert C string to Zig string slice
            s = f"    return unsafe {{ cstring_to_vstring(C.{c_func_name}("
        elif zig_res_type != "void":
            s = f"    return C.{c_func_name}("
        else:
            s = f"    C.{c_func_name}("
        for i, param_decl in enumerate(decl["params"]):
            if i > 0:
                s += ", "
            arg_name = wrap_keywords(param_decl["name"])
            arg_type = param_decl["type"]
            if is_const_struct_ptr(arg_type):
                s += f"{arg_name}"
            elif util.is_string_ptr(arg_type):
                s += f"vstring_to_cstring({arg_name})"
            else:
                s += arg_name
        if is_zig_string(zig_res_type):
            s += f")"
        s += ")"
        if is_zig_string(zig_res_type):
            s += f" }}"
        l(s)
        l("}")


def pre_parse(inp):
    global struct_types
    global enum_types
    for decl in inp["decls"]:
        kind = decl["kind"]
        if kind == "struct":
            struct_types.append(decl["name"])
        elif kind == "enum":
            enum_name = decl["name"]
            enum_types.append(enum_name)
            enum_items[enum_name] = []
            for item in decl["items"]:
                enum_items[enum_name].append(as_enum_item_name(item["name"]))


def gen_imports(inp, dep_prefixes):
    # l('const builtin = @import("builtin");')
    for dep_prefix in dep_prefixes:
        dep_module_name = module_names[dep_prefix]
        l(f"import {dep_module_name} as {dep_prefix[:-1]}")
    l("")


def gen_helpers(inp):
    l("// helper functions")
    l("// helper function to convert a C string to a Zig string slice")
    l("fn vstring_to_cstring(v_str string) &u8 {")
    l("    return v_str.str")
    l("}")


def gen_module(inp, dep_prefixes):
    l("// machine generated, do not edit")
    l("")
    l(f'module {inp["module"]}')
    gen_imports(inp, dep_prefixes)
    gen_helpers(inp)
    pre_parse(inp)
    prefix = inp["prefix"]
    for decl in inp["decls"]:
        if not decl["is_dep"]:
            kind = decl["kind"]
            if kind == "consts":
                gen_consts(decl, prefix)
            elif not check_ignore(decl["name"]):
                if kind == "struct":
                    gen_struct(decl, prefix)
                elif kind == "enum":
                    gen_enum(decl, prefix)
                elif kind == "func":
                    gen_func_c(decl, prefix)
                    gen_func_zig(decl, prefix)


def prepare():
    print("=== Generating V bindings:")
    if not os.path.isdir("sokol-v/src/sokol"):
        os.makedirs("sokol-v/src/sokol")
    if not os.path.isdir("sokol-v/src/sokol/c"):
        os.makedirs("sokol-v/src/sokol/c")


def gen(c_header_path, c_prefix, dep_c_prefixes):
    if not c_prefix in module_names:
        print(f" >> warning: skipping generation for {c_prefix} prefix...")
        return
    module_name = module_names[c_prefix]
    c_source_path = c_source_paths[c_prefix]
    print(f"  {c_header_path} => {module_name}")
    reset_globals()

    make_v_module_directory(c_prefix)
    shutil.copyfile(c_header_path, f"{c_root}/{os.path.basename(c_header_path)}")
    ir = gen_ir.gen(c_header_path, c_source_path, module_name, c_prefix, dep_c_prefixes)
    gen_module(ir, dep_c_prefixes)
    output_path = f"{module_root}/{ir['module']}/{ir['module']}.c.v"
    with open(output_path, "w", newline="\n") as f_outp:
        f_outp.write(out_lines)

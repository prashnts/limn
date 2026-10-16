# The extension's G-code commands as [gcode_macro]s, so Fluidd (and Mainsail) list them with
# their parameters: they only list macros, not the commands a Python extra registers.
#
#   python ext/limn/fluidd.py > klipper/limn_macros.cfg
#
# Each macro takes its command's name (rename_existing moves the command to _LIMN_<NAME>) and
# passes on what it was given ({rawparams}). Fluidd finds the parameters in the macro's G-code
# (params.X|default(..)): they are the ones the command reads, with its defaults, found here in
# the source (the cmd_ method and the methods it hands gcmd to). ext/tests/test_fluidd.py checks
# that the file is up to date. Not loaded by Klipper: only __init__.py is.
import ast
import os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '__init__.py')
PREFIX = '_LIMN_'
GETS = {'get', 'get_int', 'get_float'}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None             # computed (eg. 0 if self.debug else 1): no default to show


def commands(src=SRC):
    '''[(name, description, [(PARAM, default)])] in the order the extension registers them.'''
    tree = ast.parse(open(src).read())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and any(isinstance(f, ast.FunctionDef) and f.name.startswith('cmd_') for f in n.body))
    methods = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}

    def reads(fn, seen):
        '''The parameters fn reads off gcmd, and those of the methods it passes gcmd to.'''
        out = {}
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            f = n.func
            if isinstance(f.value, ast.Name) and f.value.id == 'gcmd' and f.attr in GETS \
                    and n.args and isinstance(n.args[0], ast.Constant):
                default = _literal(n.args[1]) if len(n.args) > 1 else None
                out.setdefault(n.args[0].value, default)
            elif isinstance(f.value, ast.Name) and f.value.id == 'self' and f.attr in methods \
                    and f.attr not in seen and any(isinstance(a, ast.Name) and a.id == 'gcmd' for a in n.args):
                seen.add(f.attr)
                for k, v in reads(methods[f.attr], seen).items():
                    out.setdefault(k, v)
        return out

    table = next(n for n in ast.walk(cls) if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)
                 and n.iter.elts and isinstance(n.iter.elts[0], ast.Tuple) and len(n.iter.elts[0].elts) == 3)
    out = []
    for entry in table.iter.elts:
        name, handler, desc = entry.elts
        method = handler.attr
        params = reads(methods[method], {method})
        out.append((name.value, ' '.join(_literal(desc).split()), sorted(params.items())))
    return out


def _default(v):
    if v is None:
        return "''"
    if isinstance(v, str):
        return repr(v)
    return repr(v)


def render(cmds=None):
    cmds = commands() if cmds is None else cmds
    out = ['# Made by ext/limn/fluidd.py from the extension (ext/limn/__init__.py): do not edit, make it again.',
           '# Its commands as macros, so Fluidd lists them with their parameters. Each one runs the command',
           f'# (renamed {PREFIX}<NAME>) with what it was given.', '']
    for name, desc, params in cmds:
        out += [f'[gcode_macro {name}]', f'description: {desc}', f'rename_existing: {PREFIX}{name}', 'gcode:']
        if params:
            out.append('  # what Fluidd shows as its parameters (the command reads them)')
            out += [f'  {{% set _ = params.{p}|default({_default(v)}) %}}' for p, v in params]
        out += [f'  {PREFIX}{name} {{rawparams}}', '']
    return '\n'.join(out)


if __name__ == '__main__':
    print(render(), end='')

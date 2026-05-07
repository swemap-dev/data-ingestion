import logging
import tree_sitter_python
import tree_sitter_javascript
from tree_sitter import Language, Parser, Node

logger = logging.getLogger(__name__)

# Initialize singletons for Languages
PY_LANGUAGE = Language(tree_sitter_python.language())
JS_LANGUAGE = Language(tree_sitter_javascript.language())

# --- Import extraction helpers ---

def _walk_python_imports(node: Node, imports: set):
    if node.type == 'import_statement':
        for child in node.children:
            if child.type == 'dotted_name':
                imports.add(child.text.decode('utf-8'))
    elif node.type == 'import_from_statement':
        # In tree-sitter-python, a relative import looks like:
        # relative_import ('.core.link')
        # OR it has separate import_prefix ('.') and dotted_name ('core.link') inside it.
        # It's safest to look for 'module_name' child or extract text from relative_import / dotted_name before 'import' keyword.
        module_name_node = node.child_by_field_name('module_name')
        if module_name_node:
            imports.add(module_name_node.text.decode('utf-8'))
        else:
            # Fallback for older tree-sitter-python versions
            for child in node.children:
                if child.type in ('dotted_name', 'relative_import'):
                    imports.add(child.text.decode('utf-8'))
                    break # only want the from part, not what's imported

    for child in node.children:
        _walk_python_imports(child, imports)


def _walk_js_imports(node: Node, imports: set):
    if node.type == 'import_statement':
        for child in node.children:
            if child.type == 'string':
                val = child.text.decode('utf-8').strip("'\"")
                imports.add(val)
                
    elif node.type == 'call_expression':
        # Check for require("something")
        is_require = False
        for child in node.children:
            if child.type == 'identifier' and child.text == b'require':
                is_require = True
            elif is_require and child.type == 'arguments':
                for arg in child.children:
                    if arg.type == 'string':
                        val = arg.text.decode('utf-8').strip("'\"")
                        imports.add(val)

    for child in node.children:
        _walk_js_imports(child, imports)


# --- Nesting depth measurement ---

# Node types that count as a nesting level
_PY_NESTING_TYPES = {
    'if_statement', 'elif_clause', 'else_clause',
    'for_statement', 'while_statement',
    'try_statement', 'except_clause', 'finally_clause',
}

_JS_NESTING_TYPES = {
    'if_statement', 'else_clause',
    'for_statement', 'for_in_statement', 'while_statement', 'do_statement',
    'try_statement', 'catch_clause', 'finally_clause',
    'switch_statement', 'switch_case',
}


def _measure_nesting_depth(node: Node, nesting_types: set) -> int:
    """
    Walk the AST and find the maximum nesting depth of control-flow nodes.
    """
    def _walk(n: Node, current_depth: int) -> int:
        max_depth = current_depth
        for child in n.children:
            if child.type in nesting_types:
                child_max = _walk(child, current_depth + 1)
            else:
                child_max = _walk(child, current_depth)
            max_depth = max(max_depth, child_max)
        return max_depth

    return _walk(node, 0)


# --- Class extraction ---

def _extract_python_classes(node: Node) -> list:
    """
    Extract class definitions and their base classes from a Python AST.
    Returns a list of dicts: [{"name": "Foo", "bases": ["Bar", "Baz"]}]
    """
    classes = []
    
    def _walk(n: Node):
        if n.type == 'class_definition':
            class_name = None
            bases = []
            for child in n.children:
                if child.type == 'identifier':
                    class_name = child.text.decode('utf-8')
                elif child.type == 'argument_list':
                    # Base classes are in the argument_list
                    for arg in child.children:
                        if arg.type == 'identifier':
                            bases.append(arg.text.decode('utf-8'))
                        elif arg.type == 'dotted_name':
                            bases.append(arg.text.decode('utf-8'))
            if class_name:
                classes.append({"name": class_name, "bases": bases})
        
        for child in n.children:
            _walk(child)
    
    _walk(node)
    return classes


def _extract_js_classes(node: Node) -> list:
    """
    Extract class declarations and their superclass from a JS/TS AST.
    Returns a list of dicts: [{"name": "Foo", "bases": ["Bar"]}]
    """
    classes = []
    
    def _walk(n: Node):
        if n.type == 'class_declaration':
            class_name = None
            bases = []
            for child in n.children:
                if child.type == 'identifier':
                    class_name = child.text.decode('utf-8')
                elif child.type == 'class_heritage':
                    # class Foo extends Bar
                    for heir_child in child.children:
                        if heir_child.type == 'identifier':
                            bases.append(heir_child.text.decode('utf-8'))
            if class_name:
                classes.append({"name": class_name, "bases": bases})
        
        for child in n.children:
            _walk(child)
    
    _walk(node)
    return classes


# --- Language parsers ---

def parse_python(source_code: bytes) -> dict:
    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source_code)
    
    # Calculate non-comment LOC
    lines = source_code.split(b'\n')
    loc = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(b'#'):
            loc += 1
            
    imports = set()
    _walk_python_imports(tree.root_node, imports)

    max_nesting = _measure_nesting_depth(tree.root_node, _PY_NESTING_TYPES)
    classes = _extract_python_classes(tree.root_node)
        
    return {
        "loc": loc,
        "imports": list(imports),
        "max_nesting_depth": max_nesting,
        "classes": classes,
    }


def parse_javascript(source_code: bytes) -> dict:
    parser = Parser(JS_LANGUAGE)
    tree = parser.parse(source_code)
    
    lines = source_code.split(b'\n')
    loc = 0
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not in_block:
            if stripped.startswith(b'/*'):
                if not b'*/' in stripped:
                    in_block = True
            elif stripped and not (stripped.startswith(b'//')):
                loc += 1
        else:
            if b'*/' in stripped:
                in_block = False
                
    imports = set()
    _walk_js_imports(tree.root_node, imports)

    max_nesting = _measure_nesting_depth(tree.root_node, _JS_NESTING_TYPES)
    classes = _extract_js_classes(tree.root_node)
        
    return {
        "loc": loc,
        "imports": list(imports),
        "max_nesting_depth": max_nesting,
        "classes": classes,
    }


def analyze_code_file(file_path: str, source_code: bytes) -> dict:
    """
    Analyzes the source code to extract LOC, imports, nesting depth,
    and class definitions. If the language is unsupported, it returns
    a basic LOC count.
    """
    if file_path.endswith('.py'):
        return parse_python(source_code)
    elif file_path.endswith(('.js', '.jsx', '.ts', '.tsx')):
        return parse_javascript(source_code)
    else:
        # Fallback basic LOC
        lines = source_code.split(b'\n')
        loc = len([l for l in lines if l.strip()])
        return {"loc": loc, "imports": [], "max_nesting_depth": 0, "classes": []}


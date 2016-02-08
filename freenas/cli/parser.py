#
# Copyright 2015 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################

import six
import re
import ply.lex as lex
import ply.yacc as yacc
from freenas.cli import config


def ASTObject(name, *args):
    def str(self):
        return "<{0} {1}>".format(
            self.__class__.__name__,
            ' '.join(["{0} '{1}'".format(i, getattr(self, i)) for i in args])
        )

    def init(self, *values, **kwargs):
        for idx, i in enumerate(values):
            setattr(self, args[idx], i)

        p = kwargs.get('p')
        if p:
            self.file = p.parser.filename
            self.line = p.lineno(1)
            self.column = p.lexpos(1)
            self.column_end = p.lexspan(len(p) - 1)[1]

    dct = {k: None for k in args}
    dct['__init__'] = init
    dct['__str__'] = str
    dct['__repr__'] = str
    return type(name, (), dct)


Comment = ASTObject('Comment', 'text')
Symbol = ASTObject('Symbol', 'name')
Set = ASTObject('Set', 'value')
UnaryExpr = ASTObject('UnaryExpr', 'expr', 'op')
BinaryExpr = ASTObject('BinaryExpr', 'left', 'op', 'right')
BinaryParameter = ASTObject('BinaryParameter', 'left', 'op', 'right')
Literal = ASTObject('Literal', 'value', 'type')
ExpressionExpansion = ASTObject('ExpressionExpansion', 'expr')
PipeExpr = ASTObject('PipeExpr', 'left', 'right')
FunctionCall = ASTObject('FunctionCall', 'name', 'args')
CommandCall = ASTObject('CommandCall', 'args')
Subscript = ASTObject('Subscript', 'expr', 'index')
IfStatement = ASTObject('IfStatement', 'expr', 'body', 'else_body')
AssignmentStatement = ASTObject('AssignmentStatement', 'name', 'expr')
ForStatement = ASTObject('ForStatement', 'var', 'expr', 'body')
WhileStatement = ASTObject('WhileStatement', 'expr', 'body')
UndefStatement = ASTObject('UndefStatement', 'name')
ReturnStatement = ASTObject('ReturnStatement', 'expr')
BreakStatement = ASTObject('BreakStatement')
FunctionDefinition = ASTObject('FunctionDefinition', 'name', 'args', 'body')
AnonymousFunction = ASTObject('AnonymousFunction', 'args', 'body')
Redirection = ASTObject('Redirection', 'body', 'path')


reserved = {
    'if': 'IF',
    'else': 'ELSE',
    'for': 'FOR',
    'while': 'WHILE',
    'in': 'IN',
    'function': 'FUNCTION',
    'return': 'RETURN',
    'break': 'BREAK',
    'and': 'AND',
    'or': 'OR',
    'not': 'NOT',
    'undef': 'UNDEF',
    'true': 'TRUE',
    'false': 'FALSE',
    'none': 'NULL',
}


tokens = list(reserved.values()) + [
    'ATOM', 'NUMBER', 'HEXNUMBER', 'BINNUMBER', 'OCTNUMBER', 'STRING',
    'ASSIGN', 'LPAREN', 'RPAREN', 'EQ', 'NE', 'GT', 'GE', 'LT', 'LE',
    'REGEX', 'UP', 'PIPE', 'LIST', 'COMMA', 'INC', 'DEC', 'PLUS', 'MINUS',
    'MUL', 'DIV', 'EOPEN', 'COPEN', 'LBRACE',
    'RBRACE', 'LBRACKET', 'RBRACKET', 'NEWLINE', 'COLON', 'REDIRECT'
]


def t_COMMENT(t):
    r'\#.*'
    pass


def t_IPV4(t):
    r'\d+\.\d+\.\d+\.\d+'
    t.type = 'ATOM'
    return t


def t_IPV6(t):
    r'([a-fA-F0-9]{1,4}:){1,7}:?([a-fA-F0-9:?]{1,4}){1,7}'
    t.type = 'ATOM'
    return t


def t_SIZE(t):
    r'(\d+)([kKmMgGtT][iI]?[Bb]?)'
    t.type = 'NUMBER'
    m = re.match(t_SIZE.__doc__, t.value)
    suffix = m.group(2).lower()
    value = int(m.group(1))

    if suffix == 'kib':
        value *= 1024

    if suffix in ('k', 'kb'):
        value *= 1000

    if suffix == 'mib':
        value *= 1024 * 1024

    if suffix in ('m', 'mb'):
        value *= 1000 * 1000

    if suffix == 'gib':
        value *= 1024 * 1024 * 1024

    if suffix in ('g', 'gb'):
        value *= 1000 * 1000 * 1000

    if suffix == 'tib':
        value *= 1024 * 1024 * 1024 * 1024

    if suffix in ('t', 'tb'):
        value *= 1000 * 1000 * 1000 * 1000

    t.value = value
    return t


def t_TIMEDELTA(t):
    r'(\d+:\d+\.?\d*)+'
    t.type = 'STRING'
    return t


def t_HEXNUMBER(t):
    r'0x[0-9a-fA-F]+'
    t.value = int(t.value, 16)
    return t


def t_OCTNUMBER(t):
    r'0o[0-7]+'
    t.value = int(t.value, 8)
    return t


def t_BINNUMBER(t):
    r'0b[01]+'
    t.value = int(t.value, 2)
    return t


def t_NUMBER(t):
    r'\d+'
    t.value = int(t.value)
    return t


def t_STRING(t):
    r'\"([^\\\n]|(\\.))*?\"'
    t.value = t.value[1:-1]
    return t


def t_ATOM(t):
    r'[0-9a-zA-Z_][0-9a-zA-Z_\.\/#@\:]*'
    t.type = reserved.get(t.value, 'ATOM')
    if t.type == 'TRUE':
        t.value = True
    elif t.type == 'FALSE':
        t.value = False
    elif t.type == 'NULL':
        t.value = None
    return t


t_ignore = ' \t'
t_LBRACKET = r'\['
t_RBRACKET = r'\]'
t_PIPE = r'\|'
t_EOPEN = r'\$\('
t_COPEN = r'\$\{'
t_LPAREN = r'\('
t_RPAREN = r'\)'
t_ASSIGN = r'='
t_INC = r'=\+'
t_DEC = r'=-'
t_EQ = r'=='
t_NE = r'\!='
t_GT = r'>'
t_GE = r'>='
t_LT = r'<'
t_LE = r'<='
t_PLUS = r'\+'
t_MINUS = r'-'
t_MUL = r'\*'
t_DIV = r'\/'
t_REGEX = r'~='
t_COMMA = r'\,'
t_UP = r'\.\.'
t_LIST = r'\?'
t_COLON = r':'
t_REDIRECT = r'>>'

precedence = (
    ('left', 'MINUS', 'PLUS'),
    ('left', 'MUL', 'DIV'),
    ('left', 'AND', 'OR'),
    ('right', 'NOT'),
    ('left', 'REGEX'),
    ('left', 'GT', 'LT'),
    ('left', 'GE', 'LE'),
    ('left', 'EQ', 'NE'),
    ('left', 'INC', 'DEC')
)


def t_ESCAPENL(t):
    r'\\\s*[\n\#]'
    t.lexer.lineno += 1
    pass


def t_LBRACE(t):
    r'{'
    t.lexer.parens += 1
    return t


def t_RBRACE(t):
    r'}'
    t.lexer.parens -= 1
    return t


def t_NEWLINE(t):
    r'[\n;]+'
    t.lexer.lineno += len(t.value)
    return t


def t_error(t):
    if parser.recover_errors:
        t.lexer.skip(1)
        return
    else:
        raise SyntaxError("Illegal character '%s'" % t.value[0])


def t_eof(t):
    if lexer.parens > 0:
        more = config.instance.ml.input('... ' * lexer.parens)
        if more:
            lexer.input(more + '\n')
            return lexer.token()

        return None


def p_stmt_list(p):
    """
    stmt_list : stmt_redirect
    stmt_list : stmt_redirect NEWLINE
    stmt_list : stmt_redirect NEWLINE stmt_list
    """
    if len(p) in (2, 3):
        p[0] = [p[1]]
        return

    p[0] = [p[1]] + p[3]


def p_stmt_list_2(p):
    """
    stmt_list : NEWLINE stmt_list
    """
    p[0] = p[2]


def p_stmt_redirect_1(p):
    """
    stmt_redirect : stmt
    """
    p[0] = p[1]


def p_stmt_redirect_2(p):
    """
    stmt_redirect : stmt REDIRECT ATOM
    stmt_redirect : stmt REDIRECT STRING
    """
    p[0] = Redirection(p[1], p[3], p=p)


def p_stmt(p):
    """
    stmt : if_stmt
    stmt : for_stmt
    stmt : while_stmt
    stmt : assignment_stmt
    stmt : function_definition_stmt
    stmt : return_stmt
    stmt : break_stmt
    stmt : undef_stmt
    stmt : command
    stmt : call
    """
    p[0] = p[1]


def p_block(p):
    """
    block : LBRACE stmt_list RBRACE
    """
    p[0] = p[2]


def p_block_2(p):
    """
    block : LBRACE NEWLINE stmt_list RBRACE
    """
    p[0] = p[3]


def p_block_3(p):
    """
    block : LBRACE NEWLINE RBRACE
    block : LBRACE RBRACE
    """
    p[0] = []


def p_if_stmt(p):
    """
    if_stmt : IF LPAREN expr RPAREN block
    if_stmt : IF LPAREN expr RPAREN block ELSE block
    """
    p[0] = IfStatement(p[3], p[5], p[7] if len(p) == 8 else [], p=p)


def p_for_stmt_1(p):
    """
    for_stmt : FOR LPAREN ATOM IN expr RPAREN block
    """
    p[0] = ForStatement(p[3], p[5], p[7], p=p)


def p_for_stmt_2(p):
    """
    for_stmt : FOR LPAREN ATOM COMMA ATOM IN expr RPAREN block
    """
    p[0] = ForStatement((p[3], p[5]), p[7], p[9], p=p)


def p_while_stmt(p):
    """
    while_stmt : WHILE LPAREN expr RPAREN block
    """
    p[0] = WhileStatement(p[3], p[5], p=p)


def p_assignment_stmt(p):
    """
    assignment_stmt : ATOM ASSIGN expr
    assignment_stmt : subscript_left ASSIGN expr
    """
    p[0] = AssignmentStatement(p[1], p[3], p=p)


def p_function_definition_stmt_1(p):
    """
    function_definition_stmt : FUNCTION ATOM LPAREN RPAREN block
    """
    p[0] = FunctionDefinition(p[2], [], p[5], p=p)


def p_function_definition_stmt_2(p):
    """
    function_definition_stmt : FUNCTION ATOM LPAREN function_argument_list RPAREN block
    """
    p[0] = FunctionDefinition(p[2], p[4], p[6], p=p)


def p_function_definition_stmt_3(p):
    """
    function_definition_stmt : FUNCTION ATOM LPAREN RPAREN NEWLINE block
    """
    p[0] = FunctionDefinition(p[2], [], p[6], p=p)


def p_function_definition_stmt_4(p):
    """
    function_definition_stmt : FUNCTION ATOM LPAREN function_argument_list RPAREN NEWLINE block
    """
    p[0] = FunctionDefinition(p[2], p[4], p[7], p=p)


def p_function_argument_list(p):
    """
    function_argument_list : ATOM
    function_argument_list : ATOM COMMA function_argument_list
    """
    if len(p) == 2:
        p[0] = [p[1]]

    if len(p) > 2:
        p[0] = [p[1]] + p[3]


def p_return_stmt_1(p):
    """
    return_stmt : RETURN
    """
    p[0] = ReturnStatement(Literal(None, type(None)), p=p)


def p_return_stmt_2(p):
    """
    return_stmt : RETURN expr
    """
    p[0] = ReturnStatement(p[2], p=p)


def p_break_stmt(p):
    """
    break_stmt : BREAK
    """
    p[0] = BreakStatement(p=p)


def p_undef_stmt(p):
    """
    undef_stmt : UNDEF ATOM
    """
    p[0] = UndefStatement(p[2], p=p)


def p_expr_list(p):
    """
    expr_list : expr
    expr_list : expr COMMA expr_list
    """
    if len(p) == 2:
        p[0] = [p[1]]
        return

    p[0] = [p[1]] + p[3]


def p_expr(p):
    """
    expr : symbol
    expr : literal
    expr : array_literal
    expr : dict_literal
    expr : unary_expr
    expr : binary_expr
    expr : call
    expr : subscript_expr
    expr : anon_function_expr
    expr : expr_expansion
    expr : LPAREN expr RPAREN
    expr : COPEN expr RBRACE
    """
    if len(p) == 4:
        p[0] = p[2]
        return

    p[0] = p[1]


def p_expr_expansion(p):
    """
    expr_expansion : EOPEN command RPAREN
    """
    p[0] = p[2]


def p_array_literal(p):
    """
    array_literal : LBRACKET RBRACKET
    array_literal : LBRACKET expr_list RBRACKET
    """
    if len(p) == 3:
        p[0] = Literal([], list)
        return

    p[0] = Literal(p[2], list)


def p_dict_literal_1(p):
    """
    dict_literal : LBRACE RBRACE
    dict_literal : LBRACE NEWLINE RBRACE
    """
    p[0] = Literal(dict(), dict)


def p_dict_literal_2(p):
    """
    dict_literal : LBRACE dict_pair_list RBRACE
    """
    p[0] = Literal(dict(p[2]), dict)


def p_dict_pair_list(p):
    """
    dict_pair_list : dict_pair
    dict_pair_list : dict_pair COMMA dict_pair_list
    """
    if len(p) == 2:
        p[0] = [p[1]]
        return

    p[0] = [p[1]] + p[3]


def p_dict_pair_1(p):
    """
    dict_pair : expr COLON expr
    """
    p[0] = (p[1], p[3])


def p_dict_pair_2(p):
    """
    dict_pair : NEWLINE STRING COLON expr
    dict_pair : NEWLINE STRING COLON expr NEWLINE
    """
    p[0] = (p[2], p[4])


def p_literal(p):
    """
    literal : NUMBER
    literal : HEXNUMBER
    literal : BINNUMBER
    literal : OCTNUMBER
    literal : STRING
    literal : TRUE
    literal : FALSE
    literal : NULL
    """
    p[0] = Literal(p[1], type(p[1]), p=p)


def p_symbol(p):
    """
    symbol : ATOM

    """
    p[0] = Symbol(p[1], p=p)


def p_call(p):
    """
    call : ATOM LPAREN RPAREN
    call : ATOM LPAREN expr_list RPAREN
    """
    p[0] = FunctionCall(p[1], p[3] if len(p) == 5 else [], p=p)


def p_subscript_left(p):
    """
    subscript_left : subscript_left LBRACKET expr RBRACKET
    subscript_left : symbol LBRACKET expr RBRACKET
    """
    p[0] = Subscript(p[1], p[3], p=p)


def p_subscript_expr(p):
    """
    subscript_expr : expr LBRACKET expr RBRACKET
    """
    p[0] = Subscript(p[1], p[3], p=p)


def p_anon_function_expr_1(p):
    """
    anon_function_expr : FUNCTION LPAREN RPAREN block
    """
    p[0] = AnonymousFunction([], p[4], p=p)


def p_anon_function_expr_2(p):
    """
    anon_function_expr : FUNCTION LPAREN RPAREN NEWLINE block
    """
    p[0] = AnonymousFunction([], p[5], p=p)


def p_anon_function_expr_3(p):
    """
    anon_function_expr : FUNCTION LPAREN function_argument_list RPAREN block
    """
    p[0] = AnonymousFunction(p[3], p[5], p=p)


def p_anon_function_expr_4(p):
    """
    anon_function_expr : FUNCTION LPAREN function_argument_list RPAREN NEWLINE block
    """
    p[0] = AnonymousFunction(p[3], p[6], p=p)


def p_unary_expr(p):
    """
    unary_expr : MINUS expr
    unary_expr : NOT expr
    """
    p[0] = UnaryExpr(p[2], p[1], p=p)


def p_binary_expr(p):
    """
    binary_expr : expr EQ expr
    binary_expr : expr NE expr
    binary_expr : expr GT expr
    binary_expr : expr GE expr
    binary_expr : expr LT expr
    binary_expr : expr LE expr
    binary_expr : expr PLUS expr
    binary_expr : expr MINUS expr
    binary_expr : expr MUL expr
    binary_expr : expr DIV expr
    binary_expr : expr REGEX expr
    binary_expr : expr AND expr
    binary_expr : expr OR expr
    binary_expr : expr NOT expr
    """
    p[0] = BinaryExpr(p[1], p[2], p[3], p=p)


def p_command_1(p):
    """
    command : command_item
    command : command_item parameter_list
    """
    if len(p) == 2:
        p[0] = CommandCall([p[1]], p=p)
        return

    p[0] = CommandCall([p[1]] + p[2], p=p)


def p_command_2(p):
    """
    command : command_item PIPE command
    command : command_item parameter_list PIPE command
    """
    if len(p) == 4:
        p[0] = PipeExpr(CommandCall([p[1]], p=p), p[3], p=p)
        return

    p[0] = PipeExpr(CommandCall([p[1]] + p[2], p=p), p[4], p=p)


def p_command_item_1(p):
    """
    command_item : LIST
    command_item : NUMBER
    """
    p[0] = Symbol(p[1], p=p)


def p_command_item_2(p):
    """
    command_item : DIV
    command_item : UP
    command_item : symbol
    """
    p[0] = p[1]


def p_command_item_3(p):
    """
    command_item : COPEN expr RBRACE
    """
    p[0] = ExpressionExpansion(p[2], p=p)


def p_command_item_4(p):
    """
    command_item : STRING
    """
    p[0] = Literal(p[1])


def p_parameter_list(p):
    """
    parameter_list : parameter
    parameter_list : parameter parameter_list
    """
    if len(p) == 2:
        p[0] = [p[1]]

    if len(p) > 2:
        p[0] = [p[1]] + p[2]


def p_parameter(p):
    """
    parameter : set_parameter
    parameter : binary_parameter
    """
    p[0] = p[1]


def p_parameter_error(p):
    """
    parameter : error
    """
    p[0] = None


def p_set_parameter(p):
    """
    set_parameter : unary_parameter
    set_parameter : unary_parameter COMMA set_parameter
    set_parameter : unary_parameter COMMA error
    """
    if len(p) == 4:
        if isinstance(p[3], list):
            p[0] = [p[1]] + p[3]
        else:
            p[0] = [p[1], p[3]]
        return

    p[0] = p[1]


def p_unary_parameter(p):
    """
    unary_parameter : symbol
    unary_parameter : literal
    unary_parameter : array_literal
    unary_parameter : dict_literal
    unary_parameter : COPEN expr RBRACE
    """
    if len(p) == 4:
        p[0] = ExpressionExpansion(p[2], p=p)
        return

    p[0] = p[1]


def p_unary_parameter_1(p):
    """
    unary_parameter : LIST
    """
    p[0] = Symbol(p[1])


def p_unary_parameter_2(p):
    """
    unary_parameter : UP
    unary_parameter : DIV
    """
    p[0] = p[1]


def p_binary_parameter(p):
    """
    binary_parameter : ATOM ASSIGN parameter
    binary_parameter : ATOM EQ parameter
    binary_parameter : ATOM NE parameter
    binary_parameter : ATOM GT parameter
    binary_parameter : ATOM GE parameter
    binary_parameter : ATOM LT parameter
    binary_parameter : ATOM LE parameter
    binary_parameter : ATOM REGEX parameter
    binary_parameter : ATOM INC parameter
    binary_parameter : ATOM DEC parameter
    """
    p[0] = BinaryParameter(p[1], p[2], p[3], p=p)


def p_error(p):
    if parser.recover_errors:
        if p is None:
            e = yacc.YaccSymbol()
            e.type = 'error'
            e.value = None
            e.lineno = 0
            e.lexpos = lexer.lexpos
            parser.errok()
            return e
    else:
        if not p:
            raise SyntaxError("Parse error")

        raise SyntaxError("Invalid token '{0}' at line {1}, column {2}".format(p.value, p.lineno, p.lexpos))


lexer = lex.lex()
parser = yacc.yacc(debug=False, optimize=True, write_tables=False)


def parse(s, filename, recover_errors=False):
    lexer.lineno = 1
    lexer.parens = 0
    parser.filename = filename
    parser.recover_errors = recover_errors
    return parser.parse(s, lexer=lexer, tracking=True)


def unparse(token, indent=0, oneliner=False):
    def ind(s):
        if oneliner:
            return s

        return '\t' * indent + s

    def format_block(block):
        if oneliner:
            return '; '.join(unparse(i, indent + 1, oneliner) for i in block)

        return '\n' + '\n'.join(unparse(i, indent + 1, oneliner) for i in block) + '\n'

    if isinstance(token, list):
        return '\n'.join(ind(unparse(i)) for i in token)

    if isinstance(token, Comment):
        if oneliner:
            return ''

        return '# ' + token.text

    if isinstance(token, Literal):
        if token.value is None:
            return 'none'

        if token.type in six.string_types:
            return '"{0}"'.format(token.value)

        if token.type is bool:
            return 'true' if token.value else 'false'

        if token.type is int:
            return str(token.value)

        if issubclass(token.type, list):
            return '[' + ', '.join(unparse(i) for i in token.value) + ']'

        if issubclass(token.type, dict):
            return '{' + ', '.join('{0}: {1}'.format(
                unparse(k),
                unparse(v)
            ) for k, v in token.value.items()) + '}'

        return str(token.value)

    if isinstance(token, BinaryParameter):
        return ind(''.join([token.left, token.op, unparse(token.right)]))

    if isinstance(token, Symbol):
        return ind(token.name)

    if isinstance(token, CommandCall):
        return ind(' '.join(unparse(i) for i in token.args))

    if isinstance(token, PipeExpr):
        return ind('{0} | {1}'.format(unparse(token.left), unparse(token.right)))

    if isinstance(token, FunctionCall):
        return '{0}({1})'.format(token.name, ', '.join(unparse(i) for i in token.args))

    if isinstance(token, Subscript):
        return ind('{0}[{1}]'.format(unparse(token.expr), unparse(token.index)))

    if isinstance(token, AssignmentStatement):
        if isinstance(token.name, six.string_types):
            lhs = token.name
        else:
            lhs = unparse(token.name)

        return ind('{0} = {1}'.format(lhs, unparse(token.expr)))

    if isinstance(token, BinaryExpr):
        return ind(' '.join([unparse(token.left), token.op, unparse(token.right)]))

    if isinstance(token, IfStatement):
        return ind('if ({0}) {{{1}}}'.format(
            unparse(token.expr),
            format_block(token.body)
        ))

    if isinstance(token, ForStatement):
        return ind('for ({0} in {1}) {{{2}}}'.format(
            token.var,
            unparse(token.expr),
            format_block(token.body)
        ))

    if isinstance(token, WhileStatement):
        return ind('while ({0}) {{{1}}}'.format(
            unparse(token.expr),
            format_block(token.body)
        ))

    if isinstance(token, FunctionDefinition):
        return ind('function {0}({1}) {{{2}}}'.format(
            token.name,
            ', '.join(token.args),
            format_block(token.body)
        ))

    return ''

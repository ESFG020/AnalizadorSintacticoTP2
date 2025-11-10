"""
Analizador Sintactico JSON simplificado basado en TP1 Analizador Lexico.
Version extendida: Lexer + Parser (Analizador sintactico descendente recursivo)
Detecta errores lexicos y sintacticos (panic-mode con sincronizacion).
"""
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple

#Definicion de tokens a usar en el analisis lexico para el JSON simplificado
TOKENS = [
    ("L_CORCHETE", re.compile(r"\[")),
    ("R_CORCHETE", re.compile(r"\]")),
    ("L_LLAVE", re.compile(r"\{")),
    ("R_LLAVE", re.compile(r"\}")),
    ("COMA", re.compile(r",")),
    ("DOS_PUNTOS", re.compile(r":")),
    ("LITERAL_CADENA", re.compile(r"\"(?:[^\"\\]|\\.)*\"")),#Expresion regular para cadenas JSON que empiecen y terminen con comillas dobles
    ("LITERAL_NUM", re.compile(r"[0-9]+(?:\.[0-9]+)?(?:(?:e|E)(?:\+|-)?[0-9]+)?")),#Expresion regular para números enteros y decimales con notacion cientifica opcional
    ("PR_TRUE", re.compile(r"(?:true|TRUE)")),
    ("PR_FALSE", re.compile(r"(?:false|FALSE)")),
    ("PR_NULL", re.compile(r"(?:null|NULL)")),
]

WHITESPACE = re.compile(r"\s+")#Expresion regular para espacios en blanco


@dataclass
class Token:#Clase que representa un token con su tipo, lexema y posicion
    type: str
    lexeme: str
    line: int
    col: int

    def __repr__(self):
        return f"{self.type}({self.lexeme!r})@{self.line}:{self.col}"


class Lexer:#Clase que implementa el analizador lexico Mejorado
    def __init__(self, text: str):#Inicializa el lexer con el texto de entrada y establece la posicion inicial
        self.text = text
        self.pos = 0
        self.line = 1
        self.col = 1
        self.n = len(text)

    def _advance_whitespace(self):#Funcion para avanzar sobre espacios en blanco y actualizar contadores de linea y columna
        """Consume whitespace y actualiza los contadores de linea/col"""
        m = WHITESPACE.match(self.text, self.pos)
        if not m:
            return
        span = m.group(0)
        newlines = span.count("\n")
        if newlines == 0:
            #Solo espacios en blanco o tabulaciones
            self.col += len(span)
        else:
            #Actualiza linea y columna si hay saltos de linea
            last_nl = span.rfind("\n")
            self.line += newlines
            self.col = len(span) - last_nl - 1 + 1  #La columna en la nuvea linea debe ser 1
        self.pos = m.end()

    def next_token(self) -> Token:
        """Devuelve el siguiente token(saltando espacios en blanco). Lanza ValueError en caso de error lexico."""
        while self.pos < self.n:#Mientras no se llegue al final del texto
            self._advance_whitespace()#Avanza sobre espacios en blanco
            if self.pos >= self.n:
                break

            for name, rx in TOKENS:
                m = rx.match(self.text, self.pos)
                if m:
                    lex = m.group(0)
                    tok = Token(name, lex, self.line, self.col)
                    #Avanza la posicion y actualiza columna/linea para el lexema que coincide
                    lines = lex.count("\n")
                    if lines == 0:
                        self.col += len(lex)
                    else:
                        last_nl = lex.rfind("\n")
                        self.line += lines
                        self.col = len(lex) - last_nl - 1 + 1
                    self.pos = m.end()
                    return tok

            #Si ninguna expresion coincide lanza un error lexico en la posicion actual, para reportar el caracter problematico
            bad_char = self.text[self.pos]
            raise ValueError(f"Error lexico en linea {self.line} columna {self.col}: caracter inesperado {bad_char!r}")

        return Token("EOF", "", self.line, self.col)


class Parser:
    """
    Analizador sintactico descendente recursivo para JSON simplificado
    Implementa manejo de errores en panic-mode con sincronizacion
    """

    def __init__(self, lexer: Lexer):#Inicializa el parser con una instancia del lexer y lee el primer token
        self.lexer = lexer
        self.current = self.lexer.next_token()
        self.errors: List[str] = []

    def _advance(self):
        """Consume token actual y lee el siguiente"""
        prev = self.current
        self.current = self.lexer.next_token()
        return prev

    def _match(self, expected_type: str) -> bool:
        """Si el token actual coincide con expected_type lo consume y retorna True; si no, retorna False"""
        if self.current.type == expected_type:
            self._advance()
            return True
        return False

    def _error(self, message: str):
        """Registrar un error con la posicion del token actual"""
        tok = self.current
        msg = f"[Linea {tok.line} Col {tok.col}] {message} (token actual: {tok.type} {tok.lexeme!r})"
        self.errors.append(msg)

    def _expected_close_lexeme(self, expected_token_type: str) -> str:
        """
        Dado un tipo de token esperado (R_CORCHETE o R_LLAVE) devuelve el lexema ']' o '}' para usar en mensajes de error        
        """
        mapping = {
            "R_CORCHETE": "]",
            "R_LLAVE": "}",
        }
        return mapping.get(expected_token_type, expected_token_type)

    def synchronize(self, sync_set: List[str]):
        """
        Panic-mode: consumir tokens hasta encontrar uno cuyo tipo este en sync_set o EOF
        Retorna el token en el que se sincronizo (o EOF)
        """
        while self.current.type != "EOF" and self.current.type not in sync_set:
            try:
                self._advance()
            except ValueError:
                #Existe un error lexico que impide avanzar
                break
        return self.current

    #Reglas de produccion del analizador sintactico
    def parse(self) -> bool:
        """
        Entrada: json => element EOF
        Devuelve True si no hubo errores sintacticos
        """
        self.element()
        #Espera EOF al final del archivo
        if self.current.type != "EOF":
            self._error("Se esperaba EOF al final del archivo")
        return len(self.errors) == 0

    def element(self):
        """Valida si el elemento es un object o un array"""
        if self.current.type == "L_LLAVE":
            self.object()
        elif self.current.type == "L_CORCHETE":
            self.array()
        else:
            self._error("Se esperaba 'object' o 'array' al inicio de 'element'")
            sync_tokens = ["COMA", "R_LLAVE", "R_CORCHETE", "EOF"]
            self.synchronize(sync_tokens)

    def array(self):
        """
        Valida un array JSON que puede estar vacio o contener una lista de elementos
        Si despues de '[' viene ']' entonces vacia, sino parsear element-list hasta ']' o un error
        """
        if not self._match("L_CORCHETE"):
            self._error("Se esperaba '[' para iniciar array")
            return

        if self._match("R_CORCHETE"):
            return

        #Parseamos al menos un element, luego repetimos si hay comas
        self.element()
        #Bucle: cuidamos 2 casos de error comunes:
        #Si aparece ',' consumimos y parseamos siguiente element
        #Si aparece directamente otro elemento sin ',', reportamos "falta ','" y seguimos parseando el siguiente
        while True:
            if self._match("COMA"):
                #Luego de la coma debe venir un element
                if self.current.type not in ("L_LLAVE", "L_CORCHETE"):
                    self._error("Se esperaba 'element' despues de ',' en array")
                    self.synchronize(["COMA", "R_CORCHETE", "R_LLAVE", "EOF"])
                    #Si llegamos al cierre del array, salimos del bucle
                    if self.current.type == "R_CORCHETE":
                        break
                else:
                    self.element()
                continue

            #Si no hay coma, pero directamente viene otro elemento entonces falto la coma entre elementos
            if self.current.type in ("L_LLAVE", "L_CORCHETE"):
                self._error("Falta ',' entre elementos del array")
                #Intentamos parsear el siguiente elemento para continuar
                self.element()
                continue

            #Si llega cierre del array o cualquier otro token, salimos del bucle y lo manejamos abajo
            break

        #Al terminar esperamos el cierre correcto del array
        if not self._match("R_CORCHETE"):
            expected_lex = self._expected_close_lexeme("R_CORCHETE")
            self._error(f"Falta '{expected_lex}' de cierre del array")
            self.synchronize(["COMA", "R_CORCHETE", "R_LLAVE", "EOF"])
            if self.current.type == "R_CORCHETE":
                self._advance()

    def object(self):
        """
        Verifica un object JSON que puede estar vacio o contener una lista de atributos
        """
        if not self._match("L_LLAVE"):
            self._error("Se esperaba '{' para iniciar object")
            return

        if self._match("R_LLAVE"):
            return

        #Parsear el primer atributo
        self.attribute()
        #Si hay coma, seguir parseando atributos
        while self._match("COMA"):
            #Si despues de coma no viene LITERAL_CADENA entonces error
            if self.current.type != "LITERAL_CADENA":
                self._error("Se esperaba nombre de atributo(LITERAL_CADENA) despues de ','")
                #Sincronizar hasta siguiente atributo posible o cierre
                self.synchronize(["LITERAL_CADENA", "R_LLAVE", "COMA", "R_CORCHETE", "EOF"])
            self.attribute()

        #Esperar cierre de llave
        if not self._match("R_LLAVE"):
            expected_lex = self._expected_close_lexeme("R_LLAVE")
            self._error(f"Falta '{expected_lex}' de cierre del object")
            self.synchronize(["COMA", "R_LLAVE", "R_CORCHETE", "EOF"])
            if self.current.type == "R_LLAVE":
                self._advance()

    def attribute(self):
        """Valida un atributo dentro de un object JSON"""
        if self.current.type != "LITERAL_CADENA":
            self._error("Se esperaba nombre de atributo (LITERAL_CADENA)")
            #Intenta sincronizar hasta dos puntos o coma o cierre
            self.synchronize(["DOS_PUNTOS", "COMA", "R_LLAVE", "R_CORCHETE", "EOF"])
            #Si encontramos DOS_PUNTOS lo consumimos y seguimos; si no, regresamos
            if self.current.type != "DOS_PUNTOS":
                return
        #Consumir LITERAL_CADENA(nombre del atributo)
        if self.current.type == "LITERAL_CADENA":
            self._advance()

        #Esperar dos puntos
        if not self._match("DOS_PUNTOS"):
            self._error("Se esperaba ':' despues del nombre del atributo")
            #Se sincroniza hasta un token que pueda iniciar un valor o cierre/coma
            self.synchronize(["L_LLAVE", "L_CORCHETE", "LITERAL_CADENA", "LITERAL_NUM", "PR_TRUE", "PR_FALSE", "PR_NULL", "COMA", "R_LLAVE", "EOF"])
            #En caso de que no hay token de valor valido, salimos de attribute
            if self.current.type not in ("L_LLAVE", "L_CORCHETE", "LITERAL_CADENA", "LITERAL_NUM", "PR_TRUE", "PR_FALSE", "PR_NULL"):
                return

        self.attribute_value()

    def attribute_value(self):
        """
        Valida el valor de un atributo JSON segun
        attribute-value => element | LITERAL_CADENA | LITERAL_NUM | true | false | null
        """
        if self.current.type in ("L_LLAVE", "L_CORCHETE"):
            self.element()
        elif self.current.type in ("LITERAL_CADENA", "LITERAL_NUM", "PR_TRUE", "PR_FALSE", "PR_NULL"):
            self._advance()
        else:
            self._error("Se esperaba un valor de atributo (element, LITERAL_CADENA, LITERAL_NUM, true, false o null)")
            #Sincronizar hasta coma o cierre de objeto/array para continuar
            self.synchronize(["COMA", "R_LLAVE", "R_CORCHETE", "EOF"])


# -----------------------
# Programa principal
# -----------------------

def tokenize_all(text: str) -> List[Token]:
    """Devuelve la lista completa de tokens (incluye EOF) o error lexico como token especia"""
    lex = Lexer(text)
    tokens = []
    try:
        while True:
            t = lex.next_token()
            tokens.append(t)
            if t.type == "EOF":
                break
    except ValueError as e:
        #El error lexico se registrarlo como token especial y dejar EOF
        tokens.append(Token("LEX_ERROR", str(e), lex.line, lex.col))
        #No se intenta seguir realizando el analisis lexico
        tokens.append(Token("EOF", "", lex.line, lex.col))
    return tokens


def write_tokens_file(tokens: List[Token], out_path: Path):
    """Genera un archivo con la lista de tokens, para debug o revision"""
    with out_path.open("w", encoding="utf-8") as f:
        for t in tokens:
            if t.type == "EOF":
                continue
            if t.type == "LEX_ERROR":
                f.write(f"ERROR_LEXICO {t.lexeme}\n")
            else:
                f.write(f"{t.type} {t.lexeme}\n")


def main():
    #Se define el archivo de entrada
    in_file = Path("fuente.txt")#Nombre por defecto

    if not in_file.exists():
        print(f"Archivo no encontrado: {in_file}")
        sys.exit(1)

    text = in_file.read_text(encoding="utf-8")

    #Tokenizar todo
    tokens = tokenize_all(text)
    write_tokens_file(tokens, Path("salida_tokens.txt"))
    print("Tokens escritos en salida_tokens.txt")

    #En caso de haber un error lexico, mostrar y abortar parseo
    lex_errors = [t for t in tokens if t.type == "LEX_ERROR"]
    if lex_errors:
        print("Errores lexicos detectados:")
        for e in lex_errors:
            print("  -", e.lexeme)
        print("No se realizara analisis sintactico hasta corregir errores lexicos.")
        sys.exit(1)

    #Inicializar lexer y parser
    parser = Parser(Lexer(text))
    ok = parser.parse()

    #Imprimir resultados
    if ok:
        print("Fuente sintacticamente correcto")
    else:
        print("Se encontraron errores sintacticos:")
        for err in parser.errors:
            print("  -", err)

    #Codigo de salida segun resultado
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()

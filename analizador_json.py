"""
  ANALIZADOR LEXICO + SINTACTICO PARA JSON SIMPLIFICADO
  Tarea 2 - Analisis Sintactico Descendente Recursivo
  Detecta errores lexicos y sintacticos (panic-mode con sincronizacion).

  Uso:
      python analizador_json.py                 -> fuente.txt
      python analizador_json.py entrada.json    -> archivo personalizado
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple


#Definicion de tokens a usar en el analisis lexico para el JSON simplificado
TOKENS = [
    #Delimitadores
    ("L_CORCHETE",     re.compile(r"\[")),
    ("R_CORCHETE",     re.compile(r"\]")),
    ("L_LLAVE",        re.compile(r"\{")),
    ("R_LLAVE",        re.compile(r"\}")),
    ("COMA",           re.compile(r",")),
    ("DOS_PUNTOS",     re.compile(r":")),
    #Literales
    ("LITERAL_CADENA", re.compile(r'"(?:[^"\\]|\\.)*"')),#Expresion regular para cadenas JSON que empiecen y terminen con comillas dobles
    ("LITERAL_NUM",    re.compile(r"[0-9]+(?:\.[0-9]+)?(?:(?:e|E)(?:\+|-)?[0-9]+)?")),#Expresion regular para numeros enteros y decimales con notacion cientifica opcional
    #Palabras reservadas — \b es obligatorio para no consumir prefijos de identificadores mas largos (ej: "nullXYZ" no debe tokenizarse como PR_NULL + error)
    ("PR_TRUE",        re.compile(r"(?:true|TRUE)\b")),
    ("PR_FALSE",       re.compile(r"(?:false|FALSE)\b")),
    ("PR_NULL",        re.compile(r"(?:null|NULL)\b")),
]

WHITESPACE = re.compile(r"[ \t\r]+")#Expresion regular para espacios en blanco horizontales (espacio, tabulacion)

#Clase que representa un token con su tipo, lexema y posicionen el texto (linea y columna)
@dataclass
class Token:
    """Unidad lexica: tipo, lexema, numero de linea y columna."""
    tipo:   str
    lexema: str
    linea:  int
    col:    int

    def __repr__(self):
        return f"{self.tipo}({self.lexema!r})@{self.linea}:{self.col}"


#Centinela global de fin de archivo
EOF_TOKEN = Token("EOF", "", -1, -1)

class Lexer:
    """
    Analizador lexico: Recorre el texto completo caracter a caracter, actualiza contadores de 
    linea y columna, y produce tokens con posicion exacta (linea + columna).
    Estrategia de errores:
        Ante un caracter invalido lo reporta en stderr, lo salta y continua
        tokenizando el resto del archivo (no aborta ante el primer error).
    """
    def __init__(self, texto: str):#Inicializa el lexer con el texto de entrada y establece la posicion inicial
        self.texto     = texto
        self.pos       = 0
        self.linea     = 1
        self.col       = 1
        self.n         = len(texto)
        self.errores: List[str] = []

    def _avanzar_whitespace(self):#Funcion que avanza espacios horizontales en blanco y actualiza el contador de columna
        m = WHITESPACE.match(self.texto, self.pos)
        if not m:
            return
        self.col += m.end() - self.pos
        self.pos  = m.end()

    def _avanzar_newline(self):#Consume un salto de linea (\n) y actualiza linea/columna
        self.pos   += 1
        self.linea += 1
        self.col    = 1

    def tokenizar_todo(self) -> List[Token]:
        """
        Recorre el texto completo y devuelve la lista de todos los tokens, incluyendo el token EOF al final.

        Los caracteres invalidos se reportan en stderr y se saltan; los errores quedan registrados en self.errores.
        """
        tokens: List[Token] = []

        while self.pos < self.n:
            self._avanzar_whitespace() #Saltar espacios horizontales en blanco
            if self.pos >= self.n:
                break

            if self.texto[self.pos] == "\n":#Saltar saltos de linea (actualizando contadores)
                self._avanzar_newline()
                continue

            #Intentar reconocer un token valido
            reconocido = False
            for nombre, patron in TOKENS:
                m = patron.match(self.texto, self.pos)
                if m:
                    lexema = m.group(0)
                    tokens.append(Token(nombre, lexema, self.linea, self.col))

                    #Actualizar posicion y columna (los tokens no contienen \n)
                    self.col += len(lexema)
                    self.pos  = m.end()
                    reconocido = True
                    break

            #Error lexico: caracter invalido
            if not reconocido:
                char_invalido = self.texto[self.pos]
                msg = (f"[ERROR LEXICO] Linea {self.linea} Col {self.col}: "
                       f"caracter inesperado {char_invalido!r}")
                self.errores.append(msg)
                print(msg, file=sys.stderr)
                self.col += 1
                self.pos += 1   #saltar el caracter y continuar

        #EOF explicito al final
        tokens.append(Token("EOF", "", self.linea, self.col))
        return tokens


class Parser:
    """
    Analizador sintactico descendente recursivo para JSON simplificado.
    Implementa manejo de errores en panic-mode con sincronizacion para continuar el analisis luego de detectar un error sintactico.
    """

    FIRST_ELEMENT = {"L_LLAVE", "L_CORCHETE"}

    FIRST_ATTR_VALUE = {
        "L_LLAVE", "L_CORCHETE",
        "LITERAL_CADENA", "LITERAL_NUM",
        "PR_TRUE", "PR_FALSE", "PR_NULL",
    }

    #Conjuntos de sincronizacion por no-terminal (Panic Mode)
    #Cada conjunto contiene los tokens "seguros" donde el parser puede retomar el analisis luego de descartar tokens tras un error.
    SYNC = {
        "json":            {"EOF"},
        "element":         {"R_CORCHETE", "R_LLAVE", "COMA", "EOF"},
        "array":           {"R_CORCHETE", "R_LLAVE", "COMA", "EOF"},
        "element_list":    {"R_CORCHETE", "EOF"},
        "object":          {"R_CORCHETE", "R_LLAVE", "COMA", "EOF"},
        "attributes_list": {"R_LLAVE", "EOF"},
        "attribute":       {"COMA", "R_LLAVE", "EOF"},
        "attribute_name":  {"DOS_PUNTOS", "R_LLAVE", "EOF"},
        "attribute_value": {"COMA", "R_LLAVE", "R_CORCHETE", "EOF"},
    }

    def __init__(self, tokens: List[Token]):
        self._tokens  = tokens
        self._pos     = 0
        self._errores: List[str] = []
    
    #Funciones de uso interno para manejo de tokens, consumo y errores
    @property
    def _actual(self) -> Token:
        """
        Devuelve el token actual(look-ahead de 1 simbolo) o EOF_TOKEN si se ha llegado al final de la lista de tokens.
        """
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return EOF_TOKEN

    def _consumir(self, tipo_esperado: str) -> bool:
        """
        Verifica que el token actual sea del tipo esperado y avanza el cursor.
        Si no coincide, registra un error sintactico y devuelve False sin avanzar (el token queda disponible para sincronizacion).
        """
        tok = self._actual
        if tok.tipo == tipo_esperado:
            self._pos += 1
            return True
        #Construir mensaje de error con posicion precisa
        pos_str = (f"Linea {tok.linea} Col {tok.col}"
                   if tok.tipo != "EOF" else "fin de archivo")
        self._errores.append(
            f"[ERROR SINTACTICO] {pos_str}: "
            f"se esperaba '{tipo_esperado}' "
            f"pero se encontro '{tok.tipo}' ({tok.lexema!r})"
        )
        return False

    def _sincronizar(self, non_terminal: str):
        """
        Panic Mode: descarta tokens hasta encontrar uno en el conjunto de sincronizacion del no-terminal dado (o EOF).
        """
        sync_set = self.SYNC.get(non_terminal, {"EOF"})
        while self._actual.tipo not in sync_set:
            self._pos += 1

    def _error(self, non_terminal: str, esperados: str):
        """
        Registra un error de token inesperado y activa Panic Mode para el no-terminal indicado.
        """
        tok     = self._actual
        pos_str = (f"Linea {tok.linea} Col {tok.col}"
                   if tok.tipo != "EOF" else "fin de archivo")
        self._errores.append(
            f"[ERROR SINTACTICO] {pos_str}: "
            f"token inesperado '{tok.tipo}' ({tok.lexema!r}) "
            f"al analizar <{non_terminal}>. "
            f"Se esperaba: {esperados}"
        )
        self._sincronizar(non_terminal)

    #Punto de entrada al analisis sintactico
    def analizar(self) -> bool:
        """
        Inicia el analisis desde el simbolo inicial <json>.
        Retorna True si no hubo errores sintacticos.
        """
        self._json()
        return len(self._errores) == 0
    
    #Reglas gramaticales (un metodo por no-terminal)
    def _json(self):
        """json => element EOF"""
        if self._actual.tipo in self.FIRST_ELEMENT:
            self._element()
        else:
            self._error("json", "'{' para objeto  o  '[' para array")
            #Recuperacion: si tras sincronizar hay un element, procesarlo
            if self._actual.tipo in self.FIRST_ELEMENT:
                self._element()

        #Verificar EOF estricto (no deben quedar tokens extra)
        if self._actual.tipo != "EOF":
            tok = self._actual
            self._errores.append(
                f"[ERROR SINTACTICO] Linea {tok.linea} Col {tok.col}: "
                f"tokens extra luego del elemento raiz: "
                f"'{tok.tipo}' ({tok.lexema!r})"
            )

    def _element(self):
        """element => object | array"""
        if self._actual.tipo == "L_LLAVE":
            self._object()
        elif self._actual.tipo == "L_CORCHETE":
            self._array()
        else:
            self._error("element", "'{' para objeto  o  '[' para array")

    def _array(self):
        """array => [ element-list ]  |  [ ]"""
        self._consumir("L_CORCHETE")

        if self._actual.tipo == "R_CORCHETE":
            self._consumir("R_CORCHETE")      #array vacio []
            return

        if self._actual.tipo in self.FIRST_ELEMENT:
            self._element_list()
        else:
            self._error(
                "array",
                "']' para array vacio  o  '{' / '[' para un elemento"
            )

        #Cerrar el array
        if not self._consumir("R_CORCHETE"):
            self._sincronizar("array")
            if self._actual.tipo == "R_CORCHETE":
                self._consumir("R_CORCHETE")

    def _element_list(self):
        """
        element-list => element { , element }
        (iterativa — recursion izquierda eliminada)
        """
        self._element()

        while self._actual.tipo == "COMA":
            self._consumir("COMA")
            if self._actual.tipo in self.FIRST_ELEMENT:
                self._element()
            else:
                self._error(
                    "element_list",
                    "'{' o '[' para un elemento luego de la coma"
                )
                #Si tras sincronizar aun hay un element, procesarlo
                if self._actual.tipo in self.FIRST_ELEMENT:
                    self._element()

    def _object(self):
        """object => { attributes-list }  |  { }"""
        self._consumir("L_LLAVE")

        if self._actual.tipo == "R_LLAVE":
            self._consumir("R_LLAVE")         #objeto vacio {}
            return

        if self._actual.tipo == "LITERAL_CADENA":
            self._attributes_list()
        else:
            self._error(
                "object",
                "'}' para objeto vacio  o  una cadena como nombre de atributo"
            )

        #Cerrar el objeto
        if not self._consumir("R_LLAVE"):
            self._sincronizar("object")
            if self._actual.tipo == "R_LLAVE":
                self._consumir("R_LLAVE")

    def _attributes_list(self):
        """
        attributes-list => attribute { , attribute }
        (iterativa — recursion izquierda eliminada)
        """
        self._attribute()

        while self._actual.tipo == "COMA":
            self._consumir("COMA")
            if self._actual.tipo == "LITERAL_CADENA":
                self._attribute()
            else:
                self._error(
                    "attributes_list",
                    "cadena como nombre de atributo luego de la coma"
                )
                if self._actual.tipo == "LITERAL_CADENA":
                    self._attribute()

    def _attribute(self):
        """attribute => attribute-name : attribute-value"""
        self._attribute_name()
        #Si falta el ':', sincronizar y salir — no intentar parsear el valor
        #(evita errores espurios sobre el token siguiente)
        if not self._consumir("DOS_PUNTOS"):
            self._sincronizar("attribute")
            return
        self._attribute_value()

    def _attribute_name(self):
        """attribute-name => LITERAL_CADENA"""
        if self._actual.tipo == "LITERAL_CADENA":
            self._consumir("LITERAL_CADENA")
        else:
            self._error(
                "attribute_name",
                "cadena entre comillas dobles como nombre de atributo"
            )

    def _attribute_value(self):
        """
        attribute-value => element | LITERAL_CADENA | LITERAL_NUM
                         | PR_TRUE | PR_FALSE | PR_NULL
        """
        if self._actual.tipo in self.FIRST_ELEMENT:
            self._element()
        elif self._actual.tipo in self.FIRST_ATTR_VALUE:
            self._pos += 1      #consumir el terminal directamente
        else:
            self._error(
                "attribute_value",
                "objeto, array, cadena, numero, true, false o null"
            )

    
    #Reporte de resultados
    

    def reportar(self):
        """Imprime en stdout el resultado del analisis sintactico."""
        sep = "=" * 62
        if not self._errores:
            print(sep)
            print("  RESULTADO: Fuente sintacticamente CORRECTO")
            print(sep)
        else:
            print(sep)
            print(f"  RESULTADO: {len(self._errores)} error(es) sintactico(s) encontrado(s)")
            print(sep)
            for err in self._errores:
                print(" ", err)
            print(sep)



#5. MAIN


def main():
    archivo_entrada = "fuente.txt"
    if len(sys.argv) >= 2:
        archivo_entrada = sys.argv[1]

    path = Path(archivo_entrada)
    if not path.exists():
        print(f"[ERROR] No se encontro el archivo: '{archivo_entrada}'",
              file=sys.stderr)
        sys.exit(1)

    print(f"\nAnalizando: {path}")
    print("-" * 62)

    #── Fase 1: Analisis Lexico ────────────────────────────────────────
    lexer  = Lexer(path.read_text(encoding="utf-8"))
    tokens = lexer.tokenizar_todo()

    if lexer.errores:
        print(f"  Errores lexicos   : {len(lexer.errores)}")
        print("  (el analisis sintactico continua sobre los tokens validos)")
    else:
        print("  Analisis lexico   : OK")

    #── Fase 2: Analisis Sintactico ────────────────────────────────────
    parser = Parser(tokens)
    ok     = parser.analizar()
    parser.reportar()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

from __future__ import annotations

from sigil.summarizer import summarize


def test_python_class_with_methods():
    code = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        pass\n"
        "    def baz(self, x: int) -> int:\n"
        "        return x\n"
    )
    result = summarize(code, "example.py")
    assert "class Foo:" in result
    assert "def bar(self):" in result
    assert "def baz(self, x: int) -> int:" in result


def test_python_decorators():
    code = "@app.route('/hello')\ndef hello():\n    return 'hi'\n"
    result = summarize(code, "example.py")
    assert "@app.route('/hello')" in result
    assert "def hello():" in result


def test_js_export_class():
    code = (
        "export class MyService {\n"
        "  constructor(db) {\n"
        "    this.db = db;\n"
        "  }\n"
        "  async find(id) {\n"
        "    return this.db.get(id);\n"
        "  }\n"
        "}\n"
    )
    result = summarize(code, "example.js")
    assert "export class MyService" in result


def test_commonjs_require():
    code = "const fs = require('fs');\nconst path = require('path');\n"
    result = summarize(code, "example.js")
    assert "Imports:" in result
    assert "require('fs')" in result


def test_fallback_unknown_ext():
    content = "\n".join(f"line {i}" for i in range(30))
    result = summarize(content, "file.xyz")
    assert "(30 lines)" in result
    assert "line 0" in result
    assert "line 14" in result
    assert "line 15" not in result

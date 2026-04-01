from sigil.core.tools import make_get_style_samples_tool


def test_get_style_samples_success(tmp_path):
    repo = tmp_path
    path = repo / "sample.py"
    path.write_text(
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "class Beta:\n"
        "    def run(self):\n"
        "        return alpha()\n"
        "\n"
        "def omega():\n"
        "    return 2\n"
    )

    tool = make_get_style_samples_tool(repo, None)
    result = tool.handler({"file": "sample.py", "symbols": ["alpha", "Beta"]})
    assert hasattr(result, "__await__")


async def test_get_style_samples_success_async(tmp_path):
    repo = tmp_path
    path = repo / "sample.py"
    path.write_text(
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "class Beta:\n"
        "    def run(self):\n"
        "        return alpha()\n"
        "\n"
        "def omega():\n"
        "    return 2\n"
    )

    tool = make_get_style_samples_tool(repo, None)
    result = await tool.execute({"file": "sample.py", "symbols": ["alpha", "Beta"]})
    assert "### alpha" in result.content
    assert "def alpha()" in result.content
    assert "### Beta" in result.content
    assert "class Beta" in result.content


async def test_get_style_samples_not_found(tmp_path):
    repo = tmp_path
    (repo / "sample.py").write_text("def alpha():\n    return 1\n")

    tool = make_get_style_samples_tool(repo, None)
    result = await tool.execute({"file": "sample.py", "symbols": ["missing"]})
    assert "Could not find" in result.content


async def test_get_style_samples_invalid_args(tmp_path):
    repo = tmp_path
    (repo / "sample.py").write_text("def alpha():\n    return 1\n")

    tool = make_get_style_samples_tool(repo, None)
    result = await tool.execute({"file": "sample.py", "symbols": "missing"})
    assert "Invalid symbols argument" in result.content

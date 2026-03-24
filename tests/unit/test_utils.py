from sigil.core.utils import arun


async def test_arun_exec_success():
    rc, stdout, stderr = await arun(["echo", "hello"])
    assert rc == 0
    assert stdout.strip() == "hello"


async def test_arun_exec_failure():
    rc, stdout, stderr = await arun(["false"])
    assert rc != 0


async def test_arun_shell_success():
    rc, stdout, stderr = await arun("echo hello world")
    assert rc == 0
    assert stdout.strip() == "hello world"


async def test_arun_shell_pipe():
    rc, stdout, _ = await arun("echo abc | tr a-z A-Z")
    assert rc == 0
    assert stdout.strip() == "ABC"


async def test_arun_timeout():
    rc, stdout, stderr = await arun(["sleep", "10"], timeout=0.1)
    assert rc == 1
    assert "timed out" in stderr


async def test_arun_command_not_found():
    rc, stdout, stderr = await arun(["nonexistent_command_xyz"])
    assert rc == 1
    assert "not found" in stderr.lower() or "Command not found" in stderr


async def test_arun_cwd(tmp_path):
    rc, stdout, _ = await arun(["pwd"], cwd=tmp_path)
    assert rc == 0
    assert tmp_path.name in stdout

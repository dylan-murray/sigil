import json
import time
from io import StringIO

from sigil.core.structured import StructuredEmitter


def test_emitter_stage_start_end():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("discovery")
    emitter.stage_end("discovery", findings=3, status="ok")

    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2

    start_event = json.loads(lines[0])
    assert start_event["event"] == "stage_start"
    assert start_event["stage"] == "discovery"
    assert start_event["level"] == "info"
    assert "timestamp" in start_event

    end_event = json.loads(lines[1])
    assert end_event["event"] == "stage_end"
    assert end_event["stage"] == "discovery"
    assert end_event["level"] == "info"
    assert end_event["findings_count"] == 3
    assert end_event["status"] == "ok"
    assert "duration_s" in end_event
    assert isinstance(end_event["duration_s"], float)
    assert end_event["duration_s"] >= 0
    assert "timestamp" in end_event
    assert "token_usage" in end_event


def test_emitter_stage_end_with_agent():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("analysis", agent="auditor")
    emitter.stage_end("analysis", agent="auditor", findings=5, status="ok")

    lines = buf.getvalue().strip().split("\n")
    start_event = json.loads(lines[0])
    assert start_event["agent"] == "auditor"

    end_event = json.loads(lines[1])
    assert end_event["agent"] == "auditor"


def test_emitter_run_complete():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("discovery")
    emitter.stage_end("discovery")
    emitter.run_complete(findings=10, ideas=3, prs=2, issues=1, status="ok")

    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 3

    complete_event = json.loads(lines[2])
    assert complete_event["event"] == "run_complete"
    assert complete_event["findings_count"] == 10
    assert complete_event["ideas_count"] == 3
    assert complete_event["prs_count"] == 2
    assert complete_event["issues_count"] == 1
    assert complete_event["status"] == "ok"
    assert "duration_s" in complete_event
    assert isinstance(complete_event["duration_s"], float)
    assert complete_event["duration_s"] >= 0
    assert "token_usage" in complete_event
    assert "timestamp" in complete_event


def test_emitter_duration_accuracy():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("analysis")
    time.sleep(0.1)
    emitter.stage_end("analysis", status="ok")

    lines = buf.getvalue().strip().split("\n")
    end_event = json.loads(lines[1])
    assert end_event["duration_s"] >= 0.05


def test_emitter_missing_stage_start():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_end("validation", findings=0, status="ok")

    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 1
    end_event = json.loads(lines[0])
    assert end_event["duration_s"] is None


def test_emitter_token_usage_in_stage_end():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("execution")
    emitter.stage_end("execution", status="ok")

    lines = buf.getvalue().strip().split("\n")
    end_event = json.loads(lines[1])
    usage = end_event["token_usage"]
    assert "calls" in usage
    assert "total_tokens" in usage
    assert "cost_usd" in usage


def test_emitter_run_complete_duration():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("discovery")
    time.sleep(0.05)
    emitter.stage_end("discovery")
    time.sleep(0.05)
    emitter.run_complete(findings=0, ideas=0, prs=0, issues=0, status="ok")

    lines = buf.getvalue().strip().split("\n")
    complete_event = json.loads(lines[2])
    assert complete_event["duration_s"] >= 0.05
    assert complete_event["findings_count"] == 0
    assert complete_event["ideas_count"] == 0
    assert complete_event["prs_count"] == 0
    assert complete_event["issues_count"] == 0


def test_emitter_ideas_count_in_stage_end():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("ideation")
    emitter.stage_end("ideation", ideas=7, status="ok")

    lines = buf.getvalue().strip().split("\n")
    end_event = json.loads(lines[1])
    assert end_event["ideas_count"] == 7


def test_emitter_multiple_stages():
    buf = StringIO()
    emitter = StructuredEmitter(output=buf)
    emitter.stage_start("discovery")
    emitter.stage_end("discovery", status="ok")
    emitter.stage_start("analysis")
    emitter.stage_end("analysis", findings=4, status="ok")
    emitter.run_complete(findings=4, ideas=0, prs=0, issues=0, status="ok")

    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 5

    events = [json.loads(line) for line in lines]
    assert events[0]["event"] == "stage_start"
    assert events[0]["stage"] == "discovery"
    assert events[1]["event"] == "stage_end"
    assert events[1]["stage"] == "discovery"
    assert events[2]["event"] == "stage_start"
    assert events[2]["stage"] == "analysis"
    assert events[3]["event"] == "stage_end"
    assert events[3]["stage"] == "analysis"
    assert events[4]["event"] == "run_complete"
    assert events[4]["findings_count"] == 4
    assert events[4]["prs_count"] == 0

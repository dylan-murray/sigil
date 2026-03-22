import os

import pytest

PROVIDERS = {
    "openai": {
        "env_vars": ["OPENAI_API_KEY"],
        "model": "openai/gpt-4o-mini",
        "auth_error_kwargs": {"api_key": "sk-invalid-key-for-testing"},
    },
    "anthropic": {
        "env_vars": ["ANTHROPIC_API_KEY"],
        "model": "anthropic/claude-haiku-4-5-20251001",
        "auth_error_kwargs": {"api_key": "sk-ant-invalid-key-for-testing"},
    },
    "gemini": {
        "env_vars": ["GEMINI_API_KEY"],
        "model": "gemini/gemini-2.0-flash",
        "auth_error_kwargs": {"api_key": "invalid-key-for-testing"},
    },
    "bedrock": {
        "env_vars": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"],
        "model": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
        "auth_error_kwargs": {
            "aws_access_key_id": "AKIAINVALIDKEY",
            "aws_secret_access_key": "invalid-secret",
            "aws_region_name": "us-east-1",
        },
    },
    "azure": {
        "env_vars": ["AZURE_API_KEY", "AZURE_API_BASE"],
        "model": "azure/gpt-4o-mini",
        "auth_error_kwargs": {
            "api_key": "invalid-key-for-testing",
            "api_base": "https://invalid.openai.azure.com",
        },
    },
    "mistral": {
        "env_vars": ["MISTRAL_API_KEY"],
        "model": "mistral/mistral-small-latest",
        "auth_error_kwargs": {"api_key": "invalid-key-for-testing"},
    },
}

SIMPLE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_result",
        "description": "Report the result of the task.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The answer.",
                },
            },
            "required": ["answer"],
        },
    },
}


def skip_if_no_key(provider: str) -> None:
    info = PROVIDERS[provider]
    for var in info["env_vars"]:
        if not os.environ.get(var):
            pytest.skip(f"{var} not set")


def model_for(provider: str) -> str:
    return PROVIDERS[provider]["model"]


def completion_messages(content: str = "Reply with the word 'hello'.") -> list[dict]:
    return [{"role": "user", "content": content}]


def tool_use_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": "Use the report_result tool to report the answer '42'.",
        }
    ]

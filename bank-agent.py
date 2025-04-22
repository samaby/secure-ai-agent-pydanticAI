from dataclasses import dataclass
from pydantic import BaseModel, Field
from permit import Permit
from pydantic_ai import Agent, RunContext
from typing import Any
import re
import os

PERMIT_KEY = os.environ["PERMIT_KEY"]
PERMIT_PDP = os.environ["PDP_URL"]

# Initialize Permit
permit = Permit(
    token=PERMIT_KEY,
    pdp=PERMIT_PDP,
)


@dataclass
class BankAgentDependencies:
    user_id: str
    permit_client: Permit


class BankResponse(BaseModel):
    message: str = Field(description="Response to customer query")
    sensitive_data_included: bool = Field(
        description="Whether response contains sensitive data"
    )
    caution_note: str = Field(description="Caution note if applicable", default="")


bank_agent = Agent(
    "google-gla:gemini-2.0-flash",
    deps_type=BankAgentDependencies,
    result_type=BankResponse,
    system_prompt="You are a secure banking assistant. Always verify identity and permissions before providing information.",
)


# Tool 1: Identity verification tool
@bank_agent.tool
async def verify_user_prompt(
    ctx: RunContext[BankAgentDependencies], user_query: str
) -> str:
    """Verify if user has permission to ask this query based on identity verification."""
    # Permission check with Permit.io - does user have verified identity?
    has_identity = await ctx.deps.permit_client.check(
        {
            "key": ctx.deps.user_id,
            "attributes": {"identity_verified": True},
        },
        "recieve",
        {"type": "support_response"},
    )

    if not has_identity:
        return (
            "IDENTITY_NOT_VERIFIED: Please verify your identity at example.com/verify"
        )

    return "IDENTITY_VERIFIED: User is permitted to make queries"


class SecurityError(Exception):
    pass


# Mock bank documentation with proper structure
MOCK_BANK_DOCS = [
    {
        "id": "doc_001",
        "content": "Bank accounts can be checking or savings. Minimum balance requirements apply.",
        "type": "account_info",
        "security_requirement": "standard",
    },
    {
        "id": "doc_002",
        "content": "We offer personal, business, and mortgage loans with competitive rates.",
        "type": "loan_info",
        "security_requirement": "standard",
    },
    {
        "id": "doc_003",
        "content": "Investment options include stocks, bonds, and mutual funds.",
        "type": "investment_info",
        "security_requirement": "high",
    },
    {
        "id": "doc_004",
        "content": "We use state-of-the-art encryption and multi-factor authentication.",
        "type": "security_info",
        "security_requirement": "high",
    },
]

# Mock bank account data
MOCK_BANK_ACCOUNTS = {
    "samarachi470@gmail.com": 5000.75,
    "test@example.com": 1250.30,
}

# Tool 2:
@bank_agent.tool
async def check_bank_documentation(
    ctx: RunContext[BankAgentDependencies], topic: str
) -> str:
    """Check bank documentation based on user's security level using Permit's filter_objects."""
    try:
        # Create resource instances for each document
        resources = [
            {
                "id": doc["id"],
                "type": "banking_data",
                "attributes": {
                    "data_type": doc["type"],
                    "security_requirement": doc["security_requirement"],
                },
            }
            for doc in MOCK_BANK_DOCS
        ]

        # Use Permit's filter_objects to get allowed documents
        allowed_docs = await ctx.deps.permit_client.filter_objects(
            ctx.deps.user_id, "read", {}, resources
        )

        # Get the allowed document IDs
        allowed_ids = {doc["id"] for doc in allowed_docs}

        # Filter documents based on topic and permissions
        filtered_docs = [
            doc
            for doc in MOCK_BANK_DOCS
            if doc["id"] in allowed_ids and topic.lower() in doc["type"].lower()
        ]

        if not filtered_docs:
            return "No documentation found for this topic or you don't have permission to access it."

        return filtered_docs[0]["content"]

    except Exception as e:
        raise SecurityError(f"Failed to filter documents: {str(e)}")


# Tool 3: Balance checking for secure external access
@bank_agent.tool
async def check_account_balance(ctx: RunContext[BankAgentDependencies]) -> str:
    """Check account balance via secure API."""
    # Permission check with Permit.io - can user access balance?
    has_access = await ctx.deps.permit_client.check(
        ctx.deps.user_id,
        "read",
        {
            "type": "banking_data",
            "attributes": {
                "data_type": "account_info",
                "security_requirement": "standard",
            },
        },
    )

    if not has_access:
        return "ACCESS_DENIED: You do not have permission to view account balance."

    # Mock API call using the mock data
    try:
        balance = MOCK_BANK_ACCOUNTS.get(ctx.deps.user_id, 0.0)
        return f"Your current balance is ${balance:.2f}"
    except Exception as e:
        return f"Error accessing account: {str(e)}"


# Tool 4: Response verification for response enforcement
@bank_agent.tool
async def verify_response(
    ctx: RunContext[BankAgentDependencies], response_text: str
) -> dict:
    """Verify response content and check if caution note is needed."""
    # Check if response contains numbers (potential sensitive data)
    contains_numbers = bool(re.search(r"\d", response_text))

    # Permission check with Permit.io - does user want caution notes?
    needs_caution = await ctx.deps.permit_client.check(
        ctx.deps.user_id,
        "receive_with_caution",
        {
            "type": "support_response",
            "attributes": {"contains_account_numbers": contains_numbers},
        },
    )

    result = {
        "approved": True,
        "contains_sensitive_data": contains_numbers,
        "caution_note": "",
    }

    if needs_caution and contains_numbers:
        result["caution_note"] = (
            "CAUTION: This response contains sensitive financial information. Please ensure you're in a private location."
        )

    return result


# Main handler function for your agent
async def handle_user_query(user_id: str, query: str):
    # Setup dependencies
    deps = BankAgentDependencies(
        user_id=user_id,
        permit_client=permit,
    )

    # Run the agent
    result = await bank_agent.run(query, deps=deps)
    print(result.data)
    return result.data


if __name__ == "__main__":
    import asyncio

    asyncio.run(handle_user_query("samarachi470@gmail.com", "How can i block my card?"))

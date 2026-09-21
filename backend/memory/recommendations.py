## Persist and retrieve user-scoped recommendation runs.

from uuid import uuid4

from backend.memory.dynamodb_store import (
    get_item,
    put_item,
    put_items,
    query_items,
    user_pk,
    utc_now_text,
)


## Build the private partition key that owns one recommendation run.
## Run data stays separate from the user's chronological indexes while retaining an explicit owner field.
def _run_pk(run_id):
    return f"RUN#{run_id}"


## Locate one candidate contract inside a reconstructed recommendation run.
## Decision routes use this to reject arbitrary contracts that were not part of the saved run.
def find_candidate(run, contract_symbol):
    if not run:
        return None
    return next(
        (
            candidate
            for candidate in run["candidates"]
            if candidate["contractSymbol"] == contract_symbol
        ),
        None,
    )


## Persist a complete recommendation run for one authenticated user.
## The run metadata, latest pointer, chronological index, and candidates are saved together with batched candidate writes.
## Candidates are stored with whatever columns their strategy produced, because a covered call
## prices itself on cost basis where a put prices itself on cash required.
def save_recommendation_run(
    user_id,
    candidates,
    review,
    market_context=None,
    strategy_rules=None,
    portfolio_context=None,
    memory_context=None,
    candidate_id_column="contractSymbol",
):
    run_id = str(uuid4())
    created_at = utc_now_text()
    run_partition = _run_pk(run_id)
    owner_partition = user_pk(user_id)
    candidate_records = [dict(candidate) for candidate in candidates]
    run_item = {
        "pk": run_partition,
        "sk": "META",
        "item_type": "recommendation_run",
        "id": run_id,
        "user_id": user_id,
        "created_at": created_at,
        "agent_review": review,
        "market_context": market_context or {},
        "strategy_rules": strategy_rules or {},
        "portfolio_context": portfolio_context or {},
        "memory_context": memory_context or {},
    }
    put_item(run_item)
    put_items([
        {
            "pk": owner_partition,
            "sk": f"RUN#{created_at}#{run_id}",
            "item_type": "run_index",
            "run_id": run_id,
            "created_at": created_at,
        },
        {
            "pk": owner_partition,
            "sk": "LATEST_RUN",
            "item_type": "latest_run_pointer",
            "run_id": run_id,
            "created_at": created_at,
        },
        *[
            {
                "pk": run_partition,
                # What identifies a candidate depends on what it is: a contract has a
                # symbol, while a stock recommendation is identified by its ticker.
                "sk": f"CANDIDATE#{candidate[candidate_id_column]}",
                "item_type": "recommendation_candidate",
                "id": str(uuid4()),
                "user_id": user_id,
                "recommendation_run_id": run_id,
                "candidate_id": candidate[candidate_id_column],
                "contract_symbol": candidate.get("contractSymbol"),
                "ticker_symbol": candidate["tickerSymbol"],
                "created_at": created_at,
                "candidate": candidate,
            }
            for candidate in candidate_records
        ],
    ])
    return {
        "id": run_id,
        "created_at": created_at,
        "candidates": candidate_records,
        "agent_review": review,
        "market_context": market_context or {},
        "strategy_rules": strategy_rules or {},
        "portfolio_context": portfolio_context or {},
        "memory_context": memory_context or {},
    }


## Reconstruct one recommendation run only when it belongs to the requesting user.
## The owner check closes the cross-user access path created by globally addressable run ids.
def get_recommendation_run(user_id, run_id):
    run_partition = _run_pk(run_id)
    run = get_item(run_partition, "META")
    if not run or run.get("user_id") != user_id:
        return None

    candidates = [
        item["candidate"]
        for item in query_items(run_partition, "CANDIDATE#")
    ]
    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "candidates": candidates,
        "agent_review": run.get("agent_review", {}),
        "market_context": run.get("market_context", {}),
        "strategy_rules": run.get("strategy_rules", {}),
        "portfolio_context": run.get("portfolio_context", {}),
        "memory_context": run.get("memory_context", {}),
    }


## Return the authenticated user's most recent recommendation run.
## AI Market Take uses this to compare current positions with the latest reviewed candidate set.
def get_latest_recommendation_run(user_id):
    pointer = get_item(user_pk(user_id), "LATEST_RUN")
    if not pointer:
        return None
    return get_recommendation_run(user_id, pointer["run_id"])

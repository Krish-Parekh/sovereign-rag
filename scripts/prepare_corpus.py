import argparse
import logging

import boto3

from rag.corpus import load_rows, select_articles, start_ingestion, upload, wait_for_ingestion

log = logging.getLogger("prepare_corpus")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a WixQA subset and sync the Knowledge Base")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--data-source-id", required=True)
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--region", default="ap-southeast-2")
    args = parser.parse_args()
    bucket: str = args.bucket
    knowledge_base_id: str = args.knowledge_base_id
    data_source_id: str = args.data_source_id
    count: int = args.count
    seed: int = args.seed
    region: str = args.region

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    session = boto3.session.Session(region_name=region)
    rows = load_rows()
    articles = select_articles(rows, count, seed)
    log.info("selected %d of %d rows", len(articles), len(rows))
    upload(session.client("s3"), bucket, articles)
    log.info("uploaded %d articles to s3://%s/corpus/", len(articles), bucket)
    agent = session.client("bedrock-agent")
    job = wait_for_ingestion(
        agent, knowledge_base_id, data_source_id, start_ingestion(agent, knowledge_base_id, data_source_id)
    )
    log.info("ingestion %s %s", job.status, job.statistics.model_dump_json())
    if not job.succeeded:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

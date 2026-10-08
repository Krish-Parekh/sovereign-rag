import argparse
import secrets
import sys

import httpx

from rag.signin import authorize_url, code_from_callback, exchange_code, new_pkce


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign in through Cognito managed login and write an access token")
    parser.add_argument("--domain", required=True, help="terraform output login_domain")
    parser.add_argument("--client-id", required=True, help="terraform output client_id")
    args = parser.parse_args()
    domain: str = args.domain
    client_id: str = args.client_id

    pkce = new_pkce()
    state = secrets.token_urlsafe(24)
    url = authorize_url(domain, client_id, pkce, state)
    sys.stderr.write(f"Open this link, sign in, then paste the address of the page you land on:\n\n{url}\n\n> ")
    code = code_from_callback(sys.stdin.readline().strip(), state)
    with httpx.Client(timeout=30) as client:
        token = exchange_code(client, domain, client_id, code, pkce)
    sys.stdout.write(token + "\n")


if __name__ == "__main__":
    main()

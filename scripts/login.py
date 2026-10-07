import argparse
import logging
import secrets
import sys
import webbrowser

import httpx

from rag.signin import authorize_url, code_from_callback, exchange_code, new_pkce, wait_for_callback

log = logging.getLogger("login")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign in through Cognito managed login and write an access token")
    parser.add_argument("--domain", required=True, help="terraform output login_domain")
    parser.add_argument("--client-id", required=True, help="terraform output client_id")
    args = parser.parse_args()
    domain: str = args.domain
    client_id: str = args.client_id

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    pkce = new_pkce()
    state = secrets.token_urlsafe(24)
    url = authorize_url(domain, client_id, pkce, state)
    log.info("opening %s", url)
    webbrowser.open(url)
    code = code_from_callback(wait_for_callback(), state)
    with httpx.Client(timeout=30) as client:
        tokens = exchange_code(client, domain, client_id, code, pkce)
    sys.stdout.write(tokens.access_token + "\n")


if __name__ == "__main__":
    main()

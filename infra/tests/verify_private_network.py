"""Run inside the demo VNet: python3 verify_private_network.py PREFIX."""

import ipaddress
import socket
import ssl
import sys


def verify(prefix):
    hosts = [
        f"{prefix}ai.services.ai.azure.com",
        f"{prefix}ai.openai.azure.com",
        f"{prefix}ai.cognitiveservices.azure.com",
        f"{prefix}search.search.windows.net",
        f"{prefix}st.blob.core.windows.net",
        f"{prefix}cosmos.documents.azure.com",
        f"{prefix}kv.vault.azure.net",
        f"{prefix}api.azurewebsites.net",
    ]
    expected_network = ipaddress.ip_network("10.72.1.0/24")
    context = ssl.create_default_context()
    for host in hosts:
        addresses = {a[4][0] for a in socket.getaddrinfo(
            host, 443, socket.AF_INET, socket.SOCK_STREAM)}
        assert addresses and all(ipaddress.ip_address(ip) in expected_network
                                 for ip in addresses), (host, addresses)
        with socket.create_connection((host, 443), timeout=20) as connection:
            with context.wrap_socket(connection, server_hostname=host) as tls:
                print("PASS DNS/TLS:", host, ",".join(sorted(addresses)),
                      tls.version(), flush=True)


if __name__ == "__main__":
    verify(sys.argv[1])

"""为 Hotelbeds mTLS 创建 RSA 私钥与 CSR。

私钥始终保留在本机 certs 目录；只将 .csr 文件上传到供应商后台。
运行方式：D:\\anaconda\\python.exe generate_hotelbeds_csr.py
"""

import argparse
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def build_parser():
    parser = argparse.ArgumentParser(description="生成 Hotelbeds mTLS CSR")
    parser.add_argument("--output-dir", type=Path, default=Path("certs"))
    parser.add_argument("--common-name", default="hotelbeds-client")
    parser.add_argument("--organization", default="Travel Agent Lab")
    return parser


def main():
    args = build_parser().parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    key_path = args.output_dir / "hotelbeds-client.key"
    csr_path = args.output_dir / "hotelbeds-client.csr"
    if key_path.exists() or csr_path.exists():
        raise SystemExit("目标证书文件已存在；为避免覆盖私钥，已停止执行。")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, args.organization),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Development"),
        x509.NameAttribute(NameOID.COMMON_NAME, args.common_name),
    ])
    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(
        private_key,
        hashes.SHA256(),
    )
    key_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    csr_path.write_bytes(csr.public_bytes(serialization.Encoding.PEM))
    print(f"已生成 CSR：{csr_path.resolve()}")
    print(f"私钥已保存在本机：{key_path.resolve()}")
    print("仅上传 .csr 文件；不要上传、发送或提交 .key 文件。")


if __name__ == "__main__":
    main()

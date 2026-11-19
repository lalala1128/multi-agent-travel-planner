"""为 Hotelbeds mTLS 创建 RSA 私钥与 CSR。

私钥始终保留在本机 certs 目录；只将 .csr 文件上传到供应商后台。
运行方式：D:\\anaconda\\python.exe generate_hotelbeds_csr.py
"""

import argparse
from getpass import getpass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import AttributeOID, ExtendedKeyUsageOID, NameOID


def build_parser():
    parser = argparse.ArgumentParser(description="生成 Hotelbeds mTLS CSR")
    parser.add_argument("--output-dir", type=Path, default=Path("certs"))
    parser.add_argument("--common-name", default="hotelbeds-client")
    parser.add_argument("--organization", default="Travel Agent Lab")
    parser.add_argument("--email", required=True, help="Hotelbeds 开发者门户注册邮箱")
    # 仅用于自动化验证；日常使用应让脚本隐藏输入，避免 Secret 留在 shell 历史中。
    parser.add_argument("--challenge-password", help=argparse.SUPPRESS)
    parser.add_argument("--private-key-password", help=argparse.SUPPRESS)
    return parser


def main():
    args = build_parser().parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    key_path = args.output_dir / "hotelbeds-client.key"
    csr_path = args.output_dir / "hotelbeds-client.csr"
    if key_path.exists() or csr_path.exists():
        raise SystemExit("目标证书文件已存在；为避免覆盖私钥，已停止执行。")

    challenge_password = args.challenge_password or getpass("输入 Hotelbeds Create Secret 生成的挑战密码：")
    if not challenge_password:
        raise SystemExit("挑战密码不能为空。")
    private_key_password = args.private_key_password or getpass("设置本机私钥密码：")
    if not private_key_password:
        raise SystemExit("私钥密码不能为空。")
    if args.private_key_password is None:
        confirmation = getpass("再次输入本机私钥密码：")
        if private_key_password != confirmation:
            raise SystemExit("两次私钥密码不一致。")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, args.organization),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Development"),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, args.email),
        x509.NameAttribute(NameOID.COMMON_NAME, args.common_name),
    ])
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_attribute(AttributeOID.CHALLENGE_PASSWORD, challenge_password.encode("utf-8"))
        .sign(private_key, hashes.SHA256())
    )
    key_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.BestAvailableEncryption(private_key_password.encode("utf-8")),
    ))
    csr_path.write_bytes(csr.public_bytes(serialization.Encoding.PEM))
    print(f"已生成 CSR：{csr_path.resolve()}")
    print(f"私钥已保存在本机：{key_path.resolve()}")
    print("仅上传 .csr 文件；不要上传、发送或提交 .key 文件。")


if __name__ == "__main__":
    main()

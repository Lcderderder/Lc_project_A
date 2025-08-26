import secrets
import string

# 生成一个32位的随机密钥（包含大小写字母、数字和特殊字符）
characters = string.ascii_letters + string.digits + string.punctuation
secure_key = ''.join(secrets.choice(characters) for _ in range(32))

print("生成的安全密钥：")
print(secure_key)
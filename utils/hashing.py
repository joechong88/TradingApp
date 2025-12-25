import streamlit_authenticator as stauth

password = "mj71JCsy74"

hashed = stauth.Hasher().hash(password)

print(hashed)
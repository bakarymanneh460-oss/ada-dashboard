import streamlit_authenticator as stauth

passwords = ['admin123', 'sup123', 'enum123']

hashed = stauth.Hasher(passwords).generate()

print(hashed)

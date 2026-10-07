# Security Notes

Please do not report API keys, passwords, personal data, or other secrets in public issues.

If a secret is accidentally committed:
1. Revoke/rotate it immediately with the provider.
2. Remove it from the working tree and Git history.
3. Check GitHub secret scanning and repository history before making the repository public.

The application is a demonstration project and is not ready to handle real legal documents without authentication, managed persistence, stronger access controls, and a production secrets manager.

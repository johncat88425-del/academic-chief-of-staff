# Azure AD App Registration for Outlook Integration

This guide walks you through setting up an Azure AD (Entra ID) application
to allow the Academic Chief of Staff to access your school Outlook calendar and inbox.

## Prerequisites
- A Microsoft 365 school email account with Outlook
- Access to [Azure Portal](https://portal.azure.com)

## Steps
1. Register application named `Academic Chief of Staff`
2. Redirect URI: `http://localhost:8400/callback`
3. Add API permissions: `Calendars.ReadWrite`, `Mail.Read`, `User.Read`
4. Create Client Secret and copy credentials into `.env`
5. Run `python chief_of_staff.py setup-outlook`

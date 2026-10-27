# Warehouse stock app (sample brief)

Warehouse staff must be able to register and sign in. Managers must be able to list and filter stock items.
Every change to stock must be written to an audit log.

- API in Python (FastAPI is fine); PostgreSQL preferred for the database
- Delivery with Docker
- A simple web client is enough; mobile-friendly

## Acceptance ideas

- A new user can register, sign in and sign out
- Stock items can be created, edited, filtered by name and quantity, and deleted
- Each create, edit and delete appears in the audit log with who and when

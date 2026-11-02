"""
setup_admin.py - Secure Local Administrator Bootstrap Script
=============================================================
Creates a new administrator account in ADMIN_USERS with Argon2id password hashing.
Zero hardcoded passwords. Supports interactive getpass prompts or CLI arguments.

Usage:
    Interactive mode:
        python setup_admin.py

    CLI argument mode:
        python setup_admin.py --username admin --name "System Administrator" --email admin@airline.com --password YourPasswordHere
"""

import sys
import getpass
import argparse
import os

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import HashingError
except ImportError:
    print("Error: argon2-cffi is required. Run: pip install argon2-cffi")
    sys.exit(1)

import db


def setup_admin():
    parser = argparse.ArgumentParser(description="Bootstrap Administrator Account in Oracle DB")
    parser.add_argument("--username", help="Administrator username")
    parser.add_argument("--name", help="Full name")
    parser.add_argument("--email", help="Administrator email")
    parser.add_argument("--password", help="Administrator password")
    parser.add_argument("--role", default="SUPER_ADMIN", choices=["SUPER_ADMIN", "FLIGHT_OPS", "SUPPORT"])
    args = parser.parse_args()

    print("==================================================")
    print("   AIRLINE SYSTEM - SECURE ADMIN SETUP BOOTSTRAP  ")
    print("==================================================")

    # 1. Verify that ADMIN_USERS table exists
    try:
        table_check = db.fetch_one(
            "SELECT count(*) FROM user_tables WHERE table_name = 'ADMIN_USERS'"
        )
        if not table_check or table_check[0] == 0:
            print("ERROR: Table 'ADMIN_USERS' does not exist in the database.")
            print("Please execute schema_migrations.sql in Oracle SQL Developer first.")
            sys.exit(1)
    except Exception as e:
        print(f"Database connection error: {e}")
        sys.exit(1)

    # 2. Collect admin credentials (from CLI args or interactive prompt)
    username = args.username or input("Username [e.g. admin]: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    full_name = args.name or input("Full Name [e.g. Flight Ops Lead]: ").strip()
    if not full_name:
        print("Full name cannot be empty.")
        sys.exit(1)

    email = args.email or input("Email [e.g. admin@airline.com]: ").strip()
    if not email or "@" not in email:
        print("Please enter a valid email address.")
        sys.exit(1)

    role = args.role
    if not args.username:
        role_choice = input("Role (1: SUPER_ADMIN, 2: FLIGHT_OPS, 3: SUPPORT) [Default: 1]: ").strip()
        role_map = {"1": "SUPER_ADMIN", "2": "FLIGHT_OPS", "3": "SUPPORT", "": "SUPER_ADMIN"}
        role = role_map.get(role_choice, "SUPER_ADMIN")

    # 3. Password input
    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm Password: ")
        if password != password_confirm:
            print("Passwords do not match. Aborting.")
            sys.exit(1)

    if len(password) < 8:
        print("Password must be at least 8 characters long.")
        sys.exit(1)

    # 4. Hash password with Argon2id
    ph = PasswordHasher()
    try:
        password_hash = ph.hash(password)
    except Exception as e:
        print(f"Password hashing failed: {e}")
        sys.exit(1)

    # 5. Insert into Oracle ADMIN_USERS
    conn = db.get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            # Check for existing username or email
            cursor.execute(
                "SELECT count(*) FROM ADMIN_USERS WHERE username = :1 OR email = :2",
                [username, email],
            )
            if cursor.fetchone()[0] > 0:
                print(f"Error: An administrator with username '{username}' or email '{email}' already exists.")
                conn.rollback()
                sys.exit(1)

            sql = """
                INSERT INTO ADMIN_USERS (
                    username,
                    email,
                    password_hash,
                    full_name,
                    role,
                    status,
                    created_at
                ) VALUES (
                    :username,
                    :email,
                    :password_hash,
                    :full_name,
                    :role,
                    'ACTIVE',
                    CURRENT_TIMESTAMP
                )
            """
            cursor.execute(
                sql,
                {
                    "username": username,
                    "email": email,
                    "password_hash": password_hash,
                    "full_name": full_name,
                    "role": role,
                },
            )
        conn.commit()
        print(f"\nSUCCESS: Administrator '{username}' ({role}) created successfully!")
        print("Credentials have been securely saved with Argon2id hashing.")
    except Exception as e:
        conn.rollback()
        print(f"Failed to create administrator: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    setup_admin()

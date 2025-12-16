from db.models import clear_db_schema, clear_db_rows

# Full reset (drop + recreate tables)
clear_db_schema()
print("Database schema dropped and recreated.")

# Just empty the trades table
clear_db_rows()
print("All trades deleted, schema intact.")
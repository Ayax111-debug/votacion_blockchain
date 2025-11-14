import pymysql
from pymysql.converters import conversions, convert_datetime
from pymysql.constants import FIELD_TYPE

# Ensure PyMySQL converts DATETIME/TIMESTAMP fields to Python datetimes
# so Django's timezone utilities receive datetime objects (not strings).
conversions[FIELD_TYPE.DATETIME] = convert_datetime
conversions[FIELD_TYPE.TIMESTAMP] = convert_datetime

# Use PyMySQL as a drop-in replacement for MySQLdb (mysqlclient)
# This avoids needing to compile mysqlclient on Windows.
pymysql.install_as_MySQLdb()

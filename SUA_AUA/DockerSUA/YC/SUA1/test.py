from datetime import datetime
from dateutil.parser import parse

a = 1586604994.15487
b = 1586604994.15500
dt_a = datetime.fromtimestamp(a)
dt_b = datetime.fromtimestamp(b)

print dt_a
print dt_b
print (dt_b-dt_a).total_seconds()
from dataclasses import dataclass, field
from enum import Enum
from peewee import (
    Model,
    SqliteDatabase,
    IntegerField,
    TextField,
    AutoField,
    TimestampField,
    BooleanField,
    Field,
)

db = SqliteDatabase("data.db")


class EnumField(Field):
    field_type = "TEXT"

    def __init__(self, enum_type, *args, **kwargs):
        self.enum_type = enum_type
        super().__init__(*args, **kwargs)

    def db_value(self, value):
        if isinstance(value, self.enum_type):
            return value.value
        return value

    def python_value(self, value):
        return self.enum_type(value)


class Status(Enum):
    CREATED = "created"
    CONFRIMED = "confirmed"
    REJECTED = "rejected"
    QUEUE = "queue"
    PUBLISHED = "published"


class Article(Model):
    id = AutoField()

    sender_id = IntegerField(null=False)
    sender_name = TextField(null=False)
    tid = TextField(null=True)
    time = TimestampField()

    anonymous = BooleanField()
    single = BooleanField()

    status = EnumField(Status, default=Status.CREATED)
    approve = TextField(null=True)

    mid = TextField(null=True)

    class Meta:
        database = db

    def __str__(self):
        return f"#{self.id}"


Article.create_table(safe=True)


@dataclass(slots=True)
class Session:
    id: int
    anonymous: bool
    contents: list = field(default_factory=list)

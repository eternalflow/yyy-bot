from peewee import Model, SqliteDatabase, IntegerField, CharField, TextField

database = SqliteDatabase('yyybot.sqlite')


class BaseModel(Model):
    class Meta:
        database = database


class User(BaseModel):
    tg_id = IntegerField()
    push_id = CharField()
    password = TextField()

import datetime as dt
import enum
import itertools
import logging
import os
import random
import string
import sys

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

load_dotenv()

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Status(enum.Enum):
    CREATED = 1
    STARTED = 2
    IN_PROGRESS = 3
    ABANDONED = 4
    COMPLETED = 5


class PlayerStatus(enum.Enum):
    ACTIVE = 1
    QUIT = 2


class TurnType(enum.Enum):
    DRAW = 1
    WRITE = 2


class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.String(4), primary_key=True)
    status = db.Column(db.Enum(Status))
    created_at = db.Column(db.DateTime)
    player_order = db.Column(db.JSON)

    @staticmethod
    def generate_id():
        return "".join(random.choice(string.ascii_letters) for i in range(4))

    @classmethod
    def make(cls, id=None, status=Status.CREATED, created_at=None):
        id = id or cls.generate_id()
        while cls.query.get(id):
            logger.info("generating new game id")
            id = cls.generate_id()
        game = cls(id=id, status=status, created_at=created_at or dt.datetime.utcnow())
        return game

    def add_player(self, phone):
        is_host = len(self.players) == 0
        player = GamePlayer.query.get(phone)
        if player and player.game != self:
            logger.info("player is already playing another game, not adding")
            return
        if not player:
            logger.info("creating a new player and adding them to the game")
            player = GamePlayer(
                phone=phone,
                game_id=self.id,
                is_host=is_host,
                status=PlayerStatus.ACTIVE,
            )
            db.session.add(player)
        return player

    @classmethod
    def create_game(cls):
        game_id = cls.generate_id()
        game = cls.make()
        player = cls.add_player()
        db.session.add(game)
        logger.info("committing game and player.")
        db.session.commit()
        return game

    def _generate_turn_order(self):
        """
        Generate a random send order for each turn.

        This is the order that a user's word will traverse through players.
        For example, if the order is:
        A: [B, C, D]
        Then player A's initial word will be sent to B; B will draw the word and it will be
        sent to C; C will write a word based on B's drawing; D will receive C's word and draw it.
        """

        def rotate(l, times):
            """
            Rotate a list right n times.
            """

            r = itertools.cycle(l)
            for i in range(times):
                next(r)
            return [next(r) for i in l]

        players_by_phone = {}
        send_order = [rotate(self.players, i) for i in range(len(self.players))]
        random.shuffle(send_order)
        for o in send_order:
            players_by_phone[o[0].phone] = [p.phone for p in o[1:]]
        return players_by_phone

    def start_game(self):
        if self.status != "CREATED":
            logger.info("game already started, continuing")
            return
        self.player_order = self._generate_turn_order()
        self.status = Status.STARTED
        db.session.add(self)
        db.session.commit()
        # TODO: SEND EVENT

    def is_round_over(self):
        num_players = len(self.players)
        return (
            num_players
            == GameRound.query.filter_by(
                game_id=self.id, round_number=self.current_round
            ).count()
        )

    def end_round(self):
        # TODO: SEND EVENT
        self.round += 1
        db.session.add(self)
        db.session.commit()

    @property
    def missing_players_round(self):
        all_players = set(self.players)
        this_round_responses = [r for r in game.rounds where r.round_number == self.current_round]
        players_this_round = set(r.player for r in this_round_responses)
        return len(all_players - players_this_round)

    def add_player_response(self, phone, media, body):
        type_ = TurnType.DRAW if media else TurnType.WRITE
        round = GameRound(
            game_id=self.id,
            player=phone,
            round_number=self.current_round,
            data=media if type_ == TurnType.DRAW else body,
        )
        db.session.add(round)
        db.session.commit()


class GamePlayer(db.Model):
    __tablename__ = "players"

    # only supports US numbers right now
    phone = db.Column(db.String(10), primary_key=True)
    game_id = db.Column(db.String(4), db.ForeignKey("games.id"), nullable=False)
    is_host = db.Column(db.Boolean)
    nickname = db.Column(db.String(64))
    status = db.Column(db.Enum(PlayerStatus))
    game = db.relationship("Game", backref="players")
    current_round = db.Column(db.Integer)

    @staticmethod
    def playing_other_game(phone):
        """See if player is already in another game and shouldn't be allowed to join a new one."""

        return (
            GamePlayer.query.join(Game)
            .filter(
                GamePlayer.phone == phone,
                ~Game.status.in_([Status.CREATED, Status.STARTED, Status.IN_PROGRESS]),
            )
            .count()
            > 0
        )

    def quit(self):
        self.status = PlayerStatus.QUIT
        self.game.status = Status.ABANDONED
        db.session.add_all([self, self.game])
        db.session.commit()
        # TODO: Send an event to cancel the game for everyone


class GameStart(db.Model):
    __tablename__ = "starts"
    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    game_id = db.Column(db.String(4), db.ForeignKey("games.id"), nullable=False)
    player = db.Column(db.String(10), db.ForeignKey("players.phone"))
    data = db.Column(db.Text, nullable=False)
    prompt_sent = db.Column(db.Boolean)
    prompt_sid = db.Column(db.String(40))

    game = db.relationship("Game", backref="start")


class GameRound(db.Model):
    __tablename__ = "rounds"
    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    game_id = db.Column(db.String(4), db.ForeignKey("games.id"), nullable=False)
    player = db.Column(db.String(10), db.ForeignKey("players.phone"))
    round_number = db.Column(db.Integer)
    data = db.Column(db.Text)
    turn_type = db.Column(db.Enum(TurnType))
    # sent = db.Column(db.Boolean, default=False) --> for events, did we send this info?
    prompt_sent = db.Column(db.Boolean)
    prompt_sid = db.Column(db.String(40))
    

    game = db.relationship("Game", backref="rounds")
    player = db.relationship("GamePlayer", backref="rounds")


def connect_to_db(app, db, db_path):
    """Connect the database to Flask app."""

    # Configure to use our PstgreSQL database
    app.config["SQLALCHEMY_DATABASE_URI"] = db_path
    db.app = app
    db.init_app(app)


def startup():
    from server import app

    db_path = os.environ.get("DATABASE_PATH")
    connect_to_db(app, db, db_path)


if __name__ == "__main__":
    startup()
    if sys.argv[-1] == "--create":
        db.create_all()
    print("Connected to DB.")

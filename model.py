import datetime as dt
import enum
import itertools
import logging
import os
import random
import string
import sys
from server import db
from twilio_conf import twilio_num

import tasks

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

load_dotenv()


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
    current_round = db.Column(db.Integer)

    @staticmethod
    def generate_id():
        letters_no_vowels = set(string.ascii_letters) - set("aeiouAEIOU")
        return "".join(random.choice(string.ascii_letters) for i in range(4))

    @classmethod
    def make(cls, id=None, status=Status.CREATED, created_at=None):
        id = id or cls.generate_id()
        while cls.query.get(id):
            logger.info("generating new game id")
            id = cls.generate_id()
        game = cls(
            id=id,
            status=status,
            created_at=created_at or dt.datetime.utcnow(),
            current_round=0,
        )
        return game

    def add_player(self, phone):
        is_host = len(self.players) == 0
        already_playing = GamePlayer.playing_other_game(phone)
        if already_playing:
            logger.info("player is already playing another game, not adding")
            return
        else:
            logger.info("creating a new player and adding them to the game")
            player = GamePlayer(
                phone=phone,
                game_id=self.id,
                is_host=is_host,
                status=PlayerStatus.ACTIVE,
            )

            db.session.add(player)
            db.session.commit()

        if not is_host:
            host = GamePlayer.query.filter_by(game_id=self.id, is_host=True).one()
            print('SENDING')
            tasks.send_sms.apply_async(args=[f"{phone} joined game.", None, twilio_num, host.phone, None])
        return player

    @classmethod
    def create_game(cls, phone):
        game_id = cls.generate_id()
        game = cls.make()
        db.session.add(game)
        db.session.flush()
        player = game.add_player(phone)
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
        if self.status != Status.CREATED:
            logger.info("game already started, continuing")
            return
        self.player_order = self._generate_turn_order()
        self.status = Status.STARTED
        db.session.add(self)
        db.session.commit()
        tasks.start_game.apply_async(args=[self.id])

    @property
    def current_round_is_over(self):
        num_players = len(self.players)
        return (
            num_players
            == GameRound.query.filter(
                GameRound.game_id == self.id,
                GameRound.round_number == self.current_round,
                GameRound.data.isnot(None),
            ).count()
        )

    @property
    def game_is_over(self):
        num_players = len(self.players)
        final_round = GameRound.query.filter(
            GameRound.game_id == self.id,
            GameRound.round_number == num_players - 1,
            GameRound.data.isnot(None),
        )
        return num_players == final_round.count()

    def end_round(self):
        self.current_round += 1
        db.session.add(self)
        db.session.commit()

        if self.game_is_over:
            self.status = Status.COMPLETED
            db.session.commit()
            tasks.send_gallery_view.delay(self.id) 
        else:
            tasks.start_new_round.delay(self.id)

    def add_player_response(self, phone, media, body):
        # TODO: error handling if we get a phone that's not part of this game session
        type_ = TurnType.DRAW if media else TurnType.WRITE
        round = GameRound.query.filter_by(game_id=self.id, player=phone, round_number=self.current_round).first()
        round.data = media if type_ == TurnType.DRAW else body
        round.type = type_
        db.session.commit()

        if self.current_round_is_over:
            self.end_round()


class GamePlayer(db.Model):
    __tablename__ = "players"

    # only supports US numbers right now
    phone = db.Column(db.String(10), primary_key=True)
    game_id = db.Column(db.String(4), db.ForeignKey("games.id"), nullable=False)
    is_host = db.Column(db.Boolean)
    nickname = db.Column(db.String(64))
    status = db.Column(db.Enum(PlayerStatus))
    game = db.relationship("Game", backref="players")

    @staticmethod
    def playing_other_game(phone):
        """See if player is already in another game and shouldn't be allowed to join a new one."""

        return (
            GamePlayer.query.join(Game)
            .filter(
                GamePlayer.phone == phone,
                Game.status.in_(["CREATED", "STARTED", "IN_PROGRESS"]),
            )
            .count()
            > 0
        )

    def quit(self):
        self.status = PlayerStatus.QUIT
        self.game.status = Status.ABANDONED
        db.session.add_all([self, self.game])
        db.session.commit()
        tasks.abandon_game.apply_async(args=[self.game.id, self.phone])


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


if __name__ == "__main__":
    from server import connect_to_db
    connect_to_db()


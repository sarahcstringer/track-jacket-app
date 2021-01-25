import datetime as dt
import logging
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger(__name__)
import tasks
import twilio_conf

db = SQLAlchemy()

import model

load_dotenv()


app = Flask(__name__)
db = SQLAlchemy(app)


def generate_gallery(game):
    data = []
    for i, order in enumerate(game.play_order):
        items = [i]
        for i, player_id in enumerate(order):
            round = model.GameRound.query.filter_by(
                game_id=game.id, player=player_id, round_number=i
            ).first()
            if round:
                items.append(round.data)
            else:
                items.append(None)
        data.append(items)
    return data


@app.route("/")
def home():
    return render_template("home.html", twilio_num=twilio_conf.twilio_num)

@app.route("/help")
def show_help():
    return render_template("help.html")


@app.route("/gallery/<game_id>")
def gallery(game_id):
    game = model.Game.query.get(game_id)
    if not game:
        return "That game does not exist."
    data = generate_gallery(game)
    return render_template("gallery.html", data=data)

@app.route("/join/<game_id>")
def join_game(game_id):
    game = model.Game.query.get(game_id)
    if not game:
        return "That is not a valid url to join a game."
    message = f"Join%20{game_id}"
    return render_template("join.html", to=twilio_conf.twilio_num, message=message, game_id=game_id)


def format_response(msg):
    resp = MessagingResponse()
    resp.message(msg)
    return str(resp)


def handle_empty_state(body, phone):
    if body.lower() == "create":
        game = model.Game.create_game(phone)
        return format_response(
            f"Game created. Send this join link to your friends: {os.environ.get('EIP')}/join/{game.id}\n"
            f"Text START when everyone has joined to begin the game."
        )
    elif body.lower().startswith("join"):
        game_id = body.split(" ")[-1]
        if len(game_id) != 4:
            return format_response("Did not understand game ID.")
        game = model.Game.query.get(game_id)
        if not game:
            return format_response("That game does not exist.")
        if game.status != model.Status.CREATED:
            return format_response(
                "That game has already started and cannot be joined."
            )
        player = game.add_player(phone)
        if not player:
            return format_response("Error adding player, please try again.")
        return format_response(
            f"Joined game. You will receive a message when the game has started. Visit {os.environ.get('EIP')}/help to view rules."
        )
    elif body.lower().startswith("status"):
        return format_response("You are not playing a game, status not available.")
    elif body.lower() == "start":
        return format_response(
            "Cannot start a game, you have not created one yet. Text CREATE to create a game."
        )
    elif body.lower() == "leave":
        return format_response("You are not playing a game.")
    elif body.lower() == "repeat prompt":
        return format_response("You are not playing a game.")
    return format_response(
        f"Telephone Pictionary -- visit {os.environ.get('EIP')}/help to view rules."
    )


def handle_joined_game_not_started(body, phone, player):
    if body.lower() == "start":
        if player.is_host:
            if len(player.game.players) <= 1:
                return format_response("There are no other players. Cannot start game.")
            player.game.start_game()
        else:
            return format_response("Only the host can start the game.")
    elif "status" == body.lower():
        return format_response("Waiting for host to start the game.")
    elif body.lower() == "repeat prompt":
        return format_response(
            "The game has not started, you have not received a prompt yet."
        )
    elif body.lower() == "leave":
        player.quit()


def handle_playing_submitted_response(body, phone, player):
    if (
        body.lower() == "create"
        or body.lower() == "start"
        or (body.lower().startswith("join") and len(body) == 9)
    ):
        return format_response(
            "You are in another game and must quit (text LEAVE) or complete before starting another."
        )
    elif "status" == body.lower():
        game = player.game
        num_players = len(game.players)
        num_waiting = num_players - game.current_round_responses
        return format_response(
            f"On round {game.current_round} of {num_players}, waiting on {num_waiting} players to send responses."
        )
    elif body.lower() == "leave":
        player.quit()
    elif body.lower() == "repeat prompt":
        return format_response("You have already submitted a response for this round.")


def handle_playing_waiting_for_response(body, phone, media, player):
    if media and body:
        return format_response("Please send either an image or text, not both.")
    elif "status" == body.lower():
        num_players = len(player.game.players)
        num_waiting = num_players - player.game.current_round_responses
        return format_response(
            f"On round {player.game.current_round} of {num_players}, waiting on {num_waiting} players to send responses."
        )
    elif body.lower() == "leave":
        player.quit()
    elif body.lower() == "repeat prompt":
        game = player.game
        for turn in player.game.play_order:
            if turn[game.current_round] != player.id:
                continue
            receiving_from_player = turn[game.current_round - 1]
            last_round = model.GameRound.query.filter_by(
                player=receiving_from_player,
                game_id=player.game_id,
                round_number=game.current_round - 1,
            ).first()
            action = "DRAW" if game.current_round % 2 else "DESCRIBE the image"
            body = f"{action}"
            media = None
            if action == "DESCRIBE the image":
                media = last_round.data
            else:
                body += f' "{last_round.data}"'
            tasks.send_sms.apply_async(
                args=[body, media, twilio_conf.twilio_num, player.phone, None]
            )
    player.game.add_player_response(player.id, media, body)
    return format_response("Received. Waiting for next round to start.")


@app.route("/sms", methods=["POST"])
def receive_sms():
    phone = request.form.get("From").lstrip("+1")
    body = request.form.get("Body").strip()
    media = request.form.get("MediaUrl0")
    logger.info(f"Received sms with body {body}, media {media}, from {phone}")
    already_playing = model.GamePlayer.playing_other_game(phone)
    if not already_playing:
        return handle_empty_state(body, phone)

    player = (
        model.GamePlayer.query.join(model.Game)
        .filter(
            model.Game.status.in_(["CREATED", "STARTED", "IN_PROGRESS"]),
            model.GamePlayer.phone == phone,
        )
        .first()
    )
    if player and player.game.status == model.Status.CREATED:
        return (
            handle_joined_game_not_started(body, phone, player) or MessagingResponse()
        )
    elif player and player.game.status in [
        model.Status.STARTED,
        model.Status.IN_PROGRESS,
    ]:
        game = player.game
        player_current_round = model.GameRound.query.filter_by(
            game_id=game.id, round_number=game.current_round, player=player.id
        ).first()
        if player_current_round and not player_current_round.data:
            return (
                handle_playing_waiting_for_response(body, phone, media, player)
                or MessagingResponse()
            )
        else:
            return (
                handle_playing_submitted_response(body, phone, player)
                or MessagingResponse()
            )

    return MessagingResponse()


def connect_to_db():
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_PATH")
    db.app = app
    db.init_app(app)
    db.create_all()


if __name__ == "__main__":
    db_path = os.environ.get("DATABASE_PATH")
    connect_to_db()
    app.run(debug=True)

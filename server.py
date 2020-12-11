import datetime as dt
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse

import twilio_conf

db = SQLAlchemy()

import model

# from twilio_conf import client


load_dotenv()


app = Flask(__name__)
db = SQLAlchemy(app)


@app.route("/gallery/<game_id>")
def gallery(game_id):
    data = []
    game = model.Game.query.get(game_id)
    for p in game.players:
        order = []
        first_round = model.GameRound.query.filter_by(
            game_id=game_id, player=p.phone, round_number=0
        ).one()
        order.append(first_round.data)
        for i, num in enumerate(game.player_order[p.phone][::-1]):
            order.append(
                model.GameRound.query.filter_by(
                    game_id=game_id, player=num, round_number=i + 1
                )
                .one()
                .data
            )
        data.append(order)

    return render_template("gallery.html", data=data)


@app.route("/sms", methods=["POST"])
def receive_sms():
    # Currently only accepts US numbers
    phone = request.form.get("From").lstrip("+1")
    body = request.form.get("Body")
    media = request.form.get("MediaUrl0")
    resp = MessagingResponse()
    player = model.GamePlayer.query.get(phone)
    already_playing = model.GamePlayer.playing_other_game(phone)

    if body == "CREATE":
        if already_playing:
            resp.message(
                "You are in another game and must quit or complete before starting another."
            )
            return str(resp)
        game = model.Game.create_game(phone)
        resp.message(
            f"Game created. Tell your friends to text \nJOIN {game.id}\n to {twilio_conf.twilio_num}. Text START when everyone has joined to begin the game."
        )
        return str(resp)

    elif "JOIN" in body:
        game_id = body.split(" ")[-1]
        if len(game_id) != 4:
            resp.message("Did not understand game ID.")
            return str(resp)
        game = model.Game.query.get(game_id)
        if not game:
            resp.message("That game does not exist.")
            return str(resp)
        if game.status != model.Status.CREATED:
            resp.message("That game has already started and cannot be joined.")
            return str(resp)
        player = game.add_player(phone)
        if not player:
            resp.message("Could not add player.")
            return str(resp)
        db.session.commit()
        resp.message(
            "Joined game. You will receive a message when the game has started."
        )
        return str(resp)

    elif body == "STATUS":
        if not already_playing:
            resp.message("You are not playing a game.")
            return str(resp)
        if player.game.status == model.Status.CREATED:
            resp.message("Waiting for host to start game.")
            return str(resp)
        elif player and player.game.status == model.Status.STARTED:
            resp.message("Waiting on players to send their initial words/phrases")
            return str(resp)
        elif player and player.game.status == model.Status.IN_PROGRESS:
            # resp.message(f"Round {player.game.current_round} of {len(player.game.players)}. Waiting on {player.game.missing_players_round} more responses.")
            return str(resp)

    elif body == "START":
        if player and not player.is_host:
            resp.message("Only the game's host can start the game.")
            return str(resp)
        elif player and player.game.status != model.Status.CREATED:
            resp.message("The game has already started.")
            return str(resp)
        elif player and len(player.game.players) == 1:
            resp.message("There are no other players. Cannot start game.")
            return str(resp)
        elif not player:
            resp.message("You have not started a game.")
            return str(resp)
        else:
            player.game.start_game()

    elif body == "LEAVE":
        if not already_playing:
            resp.message("You are not playing a game.")
            return str(resp)
        else:
            if not player:
                resp.message("You are not playing a game.")
                return str(resp)
            player.quit()
    elif player and player.game.status in [
        model.Status.IN_PROGRESS,
        model.Status.STARTED,
    ]:
        if media and body:
            resp.message("Please send either an image or text, not both.")
            return str(message)
        player.game.add_player_response(player.phone, media, body)
        resp.message("Received. Waiting for next round to start.")
        return str(resp)

    return str(resp)


def connect_to_db():
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_PATH")
    db.app = app
    db.init_app(app)
    db.create_all()


if __name__ == "__main__":
    db_path = os.environ.get("DATABASE_PATH")
    connect_to_db()
    app.run(debug=True)

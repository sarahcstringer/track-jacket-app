import datetime as dt
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse

import twilio_conf
import tasks

db = SQLAlchemy()

import model


load_dotenv()


app = Flask(__name__)
db = SQLAlchemy(app)


@app.route("/help")
def show_help():
    return render_template("help.html")

@app.route("/gallery/<game_id>")
def gallery(game_id):
    data = []
    game = model.Game.query.get(game_id)
    if not game:
        return "That game does not exist."
    for i, order in enumerate(game.play_order):
        items = [i] 
        for i, player_id in enumerate(order):
            round = model.GameRound.query.filter_by(
                game_id=game_id, player=player_id, round_number=i).first()
            if round:
                items.append(round.data)
            else:
                items.append(None)

        data.append(items)
    return render_template("gallery.html", data=data)


@app.route("/sms", methods=["POST"])
def receive_sms():
    # Currently only accepts US numbers
    phone = request.form.get("From").lstrip("+1")
    body = request.form.get("Body")
    media = request.form.get("MediaUrl0")
    resp = MessagingResponse()
    already_playing = model.GamePlayer.playing_other_game(phone)
    if already_playing:
        player = (
            model.GamePlayer.query.join(model.Game)
            .filter(
                model.Game.status.in_(["CREATED", "STARTED", "IN_PROGRESS"]),
                model.GamePlayer.phone == phone,
            )
            .first()
        )
    else:
        player = None

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
        resp.message(
            f"Joined game. You will receive a message when the game has started. Visit {os.environ.get('NGROK_PATH')}help to view rules."
        )
        return str(resp)

    elif "STATUS" in body:
        game_id = body.split(" ")[-1]
        if len(game_id) != 4:
            resp.message("Did not understand game ID.")
            return str(resp)
        game = model.Game.query.get(game_id)
        if not game:
            resp.message("That game does not exist.")
            return str(resp)
        if game.status == model.Status.CREATED:
            resp.message("Waiting for the host to start the game.")
            return str(resp)
        elif game.status == model.Status.STARTED:
            num_players = len(game.players)
            num_waiting = num_players - game.current_round_responses
            resp.message(f"The game has started. Waiting on {num_waiting} players to send responses.")
            return str(resp)
        elif game.status == model.Status.IN_PROGRESS:
            num_players = len(game.players)
            num_waiting = num_players - game.current_round_responses
            resp.message(f"The game is in progress. On round {game.current_round} of {num_players}, waiting on {num_waiting} players to send responses.") 
            return str(resp)
        elif game.status == model.Status.ABANDONED:
            resp.message("The game was abandoned early.")
            return str(resp)
        elif game.status == model.Status.COMPLETED:
            resp.message(f"The game has finished. View the gallery at {os.environ.get('NGROK_PATH')}gallery/{game.id}")
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

    elif body == "REPEAT PROMPT":
        if not already_playing or not player:
            resp.message("You are not playing a game.")
            return str(resp)
        elif player and player.game.status in [model.Status.CREATED, model.Status.STARTED]:
            resp.message("You have not received a prompt yet.")
            return str(resp)
        elif player and player.game.status in [model.Status.IN_PROGRESS]:
            game = player.game
            for turn in player.game.play_order:
                if turn[game.current_round] != player.id:
                    continue
                receiving_from_player = turn[game.current_round - 1]
                last_round = model.GameRound.query.filter_by(player=receiving_from_player, game_id=player.game_id, round_number=game.current_round - 1).first()
                action = "DRAW" if game.current_round % 2 else "DESCRIBE the image"
                body = f"{action}"
                media = None
                if action == "DESCRIBE the image":
                    media = last_round.data
                else:
                    body += f' "{last_round.data}"'
                tasks.send_sms.apply_async(args=[body, media, twilio_conf.twilio_num, player.phone, None])


        elif player and player.game.status in [model.Status.ABANDONED, model.Status.COMPLETED]:
            resp.message("The game has ended, you don not have a prompt.")
            return str(resp)
    elif player and player.game.status in [
        model.Status.IN_PROGRESS,
        model.Status.STARTED,
    ]:
        if media and body:
            resp.message("Please send either an image or text, not both.")
            return str(message)
        player.game.add_player_response(player.id, media, body)
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

import datetime as dt
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from twilio.twiml.messaging_response import MessagingResponse

import model

load_dotenv()


app = Flask(__name__)


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
        game = model.Game.create_game()
        # TODO: Add actual response number here
        resp.message(
            f"Game created. Tell your friends to text \nJOIN {game.id}\n to 123. Text START when everyone has joined to begin the game."
        )
        return str(resp)

    elif "JOIN" in body:
        game_id = body.split(" ")[-1]
        if len(game_id) != 4:
            resp.message("Did not understand game ID.")
            return str(resp)
        game = Game.query.get(game_id)
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
        model.db.session.commit()

    elif body == "STATUS":
        if not already_playing:
            resp.message("You are not playing a game.")
            return str(resp)
        if player.game.status == model.Status.CREATED:
            resp.message("Waiting for host to start game.")
            return str(resp)
        elif player.game.status == model.Status.STARTED:
            resp.message("Waiting on players to send their initial words/phrases")
            return str(resp)
        elif player.game.status == model.Status.IN_PROGRESS:
            resp.message(f"Round {player.game.current_round} of {len(player.game.players)}. Waiting on {player.game.missing_players_round} more responses.")
            return str(resp)


    elif body == "START":
        if not player.is_host:
            resp.message("Only the game's host can start the game.")
            return str(resp)
        elif player.game.status != model.Status.CREATED:
            resp.message("The game has already started.")
            return str(resp)
        elif len(player.game.players == 1):
            resp.message("There are no other players. Cannot start game.")
            return str(resp)
        else:
            pass

    elif body == "QUIT":
        if not already_playing:
            resp.message("You are not playing a game.")
            return str(resp)
        else:
            if not player:
                resp.message("You are not playing a game.")
                return str(resp)
            player.quit()

    elif player and player.game.status == model.Status.IN_PROGRESS:
        if media and body:
            resp.message("Please send either an image or text, not both.")
            return str(message)
        player.game.add_player_response(media, body)
        resp.message("Received. Waiting for next round to start.")
        return str(resp)

    return str(resp)

def start_game(game):
    """
    Send a prompt to everyone to say a word and send it in.
    Create GameStarts for all of those and prompt next round start event.
    """

    for p in game.players:
        # TODO: actually use Twilio
        message = send_message("FIRST ROUND: Respond with a word or phrase.")
        start = GameStart(game_id=game.id, player=p.phone, prompt_sent=True, prompt_sid=message.sid)

def send_round(game):

    for p in game.players:
        # TODO: actually use Twilio
        game.player_order[p.phone][game.current_round]
        previous_person_data = 
        action = "DRAW" if game.current_round % 2 else "DESCRIBE"
        
        message = f"Starting round {} of {len(game.players)}. {action}: {}"


if __name__ == "__main__":
    db_path = os.environ.get("DATABASE_PATH")
    model.connect_to_db(app, model.db, db_path)
    app.run(debug=True)

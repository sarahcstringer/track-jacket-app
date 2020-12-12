import os

from celery import Celery
from celery.schedules import crontab

import model
from server import connect_to_db, db
from twilio_conf import client, twilio_num

connect_to_db()

BROKER_URL = "redis://localhost:6379/0"
BACKEND_URL = "redis://localhost:6379/1"
celery_app = Celery("tasks", broker=BROKER_URL, backend=BACKEND_URL)

@celery_app.task
def update_round_information(round_id, message_sid):
    round = model.GameRound.query.get(round_id)
    round.prompt_sent = True
    round.prompt_sid = message_sid
    db.session.add(round)
    db.session.commit()


@celery_app.task
def send_sms(body, media, from_, to, round_id=None):
    message = client.messages.create(body=body, from_=from_, to=to, media_url=media)
    if round_id:
        update_round_information.apply_async(args=[round_id, message.sid])


@celery_app.task
def abandon_game(game_id, abandoner):
    game = model.Game.query.get(game_id)
    for p in game.players:
        if p.phone == abandoner:
            body = f"You have left the game."
        else:
            body = f"A player abandoned the game, it has now ended."
        send_sms.apply_async(args=[body, None, twilio_num, p.phone, None])


@celery_app.task
def start_game(game_id):
    """Send a prompt to everyone to say a word and send it in."""
    game = model.Game.query.get(game_id)
    game.status = model.Status.IN_PROGRESS
    for p in game.players:
        body = "FIRST ROUND: Respond with a word or phrase."
        round = model.GameRound(
            game_id=game.id,
            player=p.id,
            turn_type=model.TurnType.WRITE,
            round_number=game.current_round,
        )
        db.session.add(round)
        db.session.commit()
        send_sms.apply_async(args=[body, None, twilio_num, p.phone, round.id])


@celery_app.task
def start_new_round(game_id):
    game = model.Game.query.get(game_id)
    for turn in game.play_order:
        # ex: [7, 5, 6]
        receiving_from_player = turn[game.current_round - 1]  # last round's turn
        send_to_player = turn[game.current_round]
        send_to_phone = model.GamePlayer.query.get(send_to_player).phone
        last_round = model.GameRound.query.filter_by(
            player=receiving_from_player,
            game_id=game.id,
            round_number=game.current_round - 1,
        ).first()
        action = "DRAW" if game.current_round % 2 else "DESCRIBE the image"
        body = (
            f"Starting round {game.current_round + 1} of {len(game.players)}. {action}"
        )
        media = None
        if action == "DESCRIBE the image":
            media = last_round.data
        else:
            body += f' "{last_round.data}"'
        round = model.GameRound(
            game_id=game.id,
            player=send_to_player,
            turn_type=model.TurnType.DRAW if game.current_round % 2 else model.TurnType.WRITE,
            round_number=game.current_round,
        )
        db.session.add(round)
        db.session.commit()
        send_sms.apply_async(args=[body, media, twilio_num, send_to_phone, round.id])


@celery_app.task
def send_round_update(phone_nums, num_remaining):
    for p in phone_nums:
        body = f"A player sent a response. Waiting on {num_remaining} other responsesin this round."
        send_sms.apply_async(args=[body, None, twilio_num, p, None])


@celery_app.task
def send_gallery_view(game_id):
    game = model.Game.query.get(game_id)
    for p in game.players:
        body = f"Game is over! Visit {os.environ.get('NGROK_PATH')}gallery/{game_id} to view the final results."
        send_sms.apply_async(args=[body, None, twilio_num, p.phone, None])

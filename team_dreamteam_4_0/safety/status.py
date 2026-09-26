"""Определение рабочего статуса AMR платформы."""


def determine_status(
    v_odom: float,
    w_odom: float = 0.0,
    is_arrived: bool = False,
    is_lost: bool = False,
    is_stopped: bool = False,
    is_slowed: bool = False,
    is_estop: bool = False,
    allow_slowed: bool = False,
) -> str:
    """Определить рабочий статус AMR.

    Соответствует правилам оценки:
    - статус обязан быть 'moving', когда |v_odom| >= 0.05, чтобы не допустить status_mismatch (-2);
    - статус 'arrived', когда выполнено условие прибытия в док;
    - статус 'waiting', когда платформа стоит (|v_odom| < 0.05) из-за препятствия, человека или паузы;
    - статус 'lost', когда поза потеряна И платформа уже остановилась;
    - статус 'estop', когда сработало экстренное торможение;
    - если allow_slowed=True и робот движется при сниженном ограничении скорости, возвращается 'slowed'.
    """
    if is_arrived:
        return "arrived"
    if is_estop:
        return "estop"

    # Порог движения из критериев оценки: moving_v = 0.05 м/с
    if abs(v_odom) >= 0.05 or abs(w_odom) >= 0.10:
        if allow_slowed and is_slowed:
            return "slowed"
        return "moving"

    # Стационарное состояние (|v_odom| < 0.05)
    if is_lost:
        return "lost"
    if is_stopped:
        return "waiting"
    if is_slowed and allow_slowed:
        return "slowed"

    return "waiting"

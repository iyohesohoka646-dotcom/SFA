def evaluate(context, parameters):
    """A program receives frozen evidence, never a live mutable data object."""
    count = len(context['snapshots'])
    return {'status': 'pass' if count >= parameters['minimum'] else 'fail',
            'message': 'Observed input count checked', 'data': {'input_count': count}}

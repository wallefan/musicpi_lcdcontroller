import pygame

class FakeLCD:
    def __init__(self, surface: pygame.Surface):
        self.surface = surface
        pygame.
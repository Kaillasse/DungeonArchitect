#gere les differents modes de jeu : menu, editeur de map, et rogue like top down

import sys
import pygame
from core.creator import Creator
from core.explorator import Explorator
from core.gamestate import GameState

class GameManager:
    def __init__(self, screen):
        self.screen = screen
        self.state = GameState.CREATOR
        self.running = True
        self.clock = pygame.time.Clock()
        self.creator = Creator(self)
        self.explorator = Explorator(self)
        self.world = None
        self.character = None
        self.camera = None
        self.npc_manager = None
        self.interaction_ui = None
        self.previous_state = None  # Pour retourner au state précédent
        

    def initialize_world(self):
        if self.world is None:
            self.world = World(self.screen)
            self.world.session = self.session
            self.npc_manager = PNJManager(self.world)
            self.npc_manager.spawn_npcs()
            
            if self.interaction_ui is None:
                self.interaction_ui = InteractionUI(
                    self.screen.get_width(), 
                    self.screen.get_height(), 
                    session=self.session
                )
        return self.world

    def initialize_character(self):
        if self.character is None:
            session = self.get_current_session()
            world = self.initialize_world()
            self.character = Character(session, world)
        return self.character

    def initialize_camera(self):
        if self.camera is None:
            self.camera = Camera(self.screen.get_width(), self.screen.get_height())
            character = self.initialize_character()
            self.camera.center_on_character(character)
        return self.camera


    def handle_exploration(self):
        world = self.initialize_world()
        character = self.initialize_character()
        camera = self.initialize_camera()
        quest_button = self.initialize_quest_button()

        exploring = True

        while exploring:
            dt = self.clock.tick(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        exploring = False
                        self.state = GameState.MENU
                    elif event.key == pygame.K_F1:
                        # Debug: print entity positions
                        world.print_entity_positions()
                
                # Gestion du bouton de quête
                quest_result = self.handle_quest_button_event(event)
                if quest_result == "quest_table_opened":
                    exploring = False
                    continue
                
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        mouse_x, mouse_y = pygame.mouse.get_pos()
                        world_x, world_y = camera.screen_to_world(mouse_x, mouse_y)
                        if self.npc_manager:
                            clicked_npc = self.npc_manager.handle_click(world_x, world_y)
                            if clicked_npc:
                                self.interaction_ui.start_interaction(character, clicked_npc, self.session)
                                self.state = GameState.INTERACTION
                                exploring = False

            keys = pygame.key.get_pressed()
            character.handle_input(keys)
            character.update(dt)
            camera.center_on_character(character)

            if self.npc_manager:
                self.npc_manager.update(dt)

            # Met à jour le bouton de quête
            quest_button.update()

            self.screen.fill((20, 30, 40))
            world.draw(self.screen, camera)
            character.draw(self.screen, camera)
            
            if self.npc_manager:
                self.npc_manager.draw(self.screen, camera)
            
            # Dessine le bouton de quête
            quest_button.draw(self.screen)

            pygame.display.flip()

    def handle_interaction(self):
        world = self.initialize_world()
        character = self.initialize_character()
        camera = self.initialize_camera()
        
        interacting = True
        
        while interacting:
            dt = self.clock.tick(60)
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                
                dialogue_action = self.interaction_ui.handle_event(event)
                if dialogue_action == "end" or (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN):
                    self.interaction_ui.end_interaction()
                    self.state = GameState.EXPLORATION
                    interacting = False

            mouse_pos = pygame.mouse.get_pos()
            self.interaction_ui.update(mouse_pos)
            
            self.screen.fill((20, 30, 40))
            world.draw(self.screen, camera)
            character.draw(self.screen, camera)
            
            if self.npc_manager:
                self.npc_manager.draw(self.screen, camera)
            
            self.interaction_ui.render(self.screen)
            pygame.display.flip()
   
  
    def run(self):
        while self.running:
            if self.state == GameState.CREATOR:
                self.creator.run()
            elif self.state == GameState.EXPLORATION:
                self.explorator.run()
            elif self.state == GameState.INTERACTION:
                self.handle_interaction()
                self.clock.tick(60)
